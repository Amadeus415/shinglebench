"""Grade a round with LLM judges, then aggregate judges + humans into results.json.

results.json is the single source of truth for the dashboard, the round report and the public
site, so every number shown anywhere comes from the same file.
"""

from __future__ import annotations

import json
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import yaml

from ..config import ROOT
from ..tasks import get_task
from .evidence import packet
from .judges import judge_absolute, judge_pairwise
from .rubric import RUBRIC_VERSION, dim_ids
from .stats import bradley_terry, bt_bootstrap, elo_from_bt, hier_bootstrap, krippendorff_alpha, mean, spearman


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def round_runs(round_dir: Path) -> list[dict]:
    out = []
    for d in sorted(round_dir.iterdir()):
        b = d / "bundle"
        if (b / "checks.json").exists():
            m = json.loads((b / "manifest.json").read_text())
            out.append({"dir": d, "bundle": b, "manifest": m, "checks": json.loads((b / "checks.json").read_text())})
    return out


def grade_round(round_dir: Path, judges: list[str], force: bool = False, echo=print) -> None:
    runs = round_runs(round_dir)
    jdir = round_dir / "judgments"
    abs_rows = [] if force else _jsonl(jdir / "llm_absolute.jsonl")
    pair_rows = [] if force else _jsonl(jdir / "llm_pairwise.jsonl")
    have_abs = {(r["run_id"], r["judge"]) for r in abs_rows}
    have_pair = {(r["a"], r["b"], r["judge"]) for r in pair_rows}
    packets = {}
    for r in runs:
        task = get_task(r["manifest"]["task_id"])
        packets[r["manifest"]["run_id"]] = (packet(r["bundle"], task), task, r["manifest"]["model_family"], r["manifest"]["model"])
    for rid, (p, task, fam, _) in packets.items():
        for j in judges:
            if (rid, j) not in have_abs:
                abs_rows.append(judge_absolute(j, p, task, fam))
    echo(f"absolute judgments: {len(abs_rows)}")
    by_task = defaultdict(list)
    for rid, (p, task, fam, model) in packets.items():
        by_task[task.id].append((rid, model))
    for tid, items in by_task.items():
        task = get_task(tid)
        for (ra, ma), (rb, mb) in combinations(sorted(items), 2):
            if ma == mb:
                continue
            for j in judges:
                if (ra, rb, j) not in have_pair:
                    pair_rows.append(judge_pairwise(j, packets[ra][0], packets[rb][0], task))
    echo(f"pairwise judgments: {len(pair_rows)} (each = two position-swapped passes)")
    _write_jsonl(jdir / "llm_absolute.jsonl", abs_rows)
    _write_jsonl(jdir / "llm_pairwise.jsonl", pair_rows)


def aggregate(round_dir: Path, human_abs: list[dict] | None = None, human_pair: list[dict] | None = None) -> dict:
    cfg = yaml.safe_load((ROOT / "config" / "aggregation.yaml").read_text())
    w_h, w_l = cfg["combine"]["human"], cfg["combine"]["llm"]
    reps = cfg.get("bootstrap_reps", 2000)
    meta = json.loads((round_dir / "round.json").read_text())
    runs = round_runs(round_dir)
    abs_rows = _jsonl(round_dir / "judgments" / "llm_absolute.jsonl")
    pair_rows = _jsonl(round_dir / "judgments" / "llm_pairwise.jsonl")
    human_abs = [h for h in (human_abs or []) if not h.get("is_gold") and not h.get("is_attention") and not h.get("excluded")]
    human_pair = human_pair or []
    dims = dim_ids()

    llm_by_run = defaultdict(list)
    for r in abs_rows:
        llm_by_run[r["run_id"]].append(r)
    hum_by_run = defaultdict(list)
    for h in human_abs:
        hum_by_run[h["run_id"]].append(h)

    run_rows = []
    for r in runs:
        m, c = r["manifest"], r["checks"]
        rid = m["run_id"]
        js = llm_by_run.get(rid, [])
        injection = c["results"].get("integrity", {}).get("grader_injection_detected", False)
        if injection and js and cfg.get("injection_policy") == "strictest_judge_and_flag":
            js = [min(js, key=lambda x: x["scores"]["overall"])]
        llm = {d: mean([j["scores"][d] for j in js]) for d in dims}
        hum = {d: mean([h["scores"][d] for h in hum_by_run.get(rid, []) if h["scores"].get(d) is not None]) for d in dims}
        comb = {d: (w_h * hum[d] + w_l * llm[d]) / (w_h + w_l) if hum[d] is not None and llm[d] is not None else (llm[d] if hum[d] is None else hum[d]) for d in dims}
        weeks = [json.loads(p.read_text())["totals"] for p in sorted((r["bundle"] / "market").glob("week_*.json"))]
        run_rows.append({
            "run_id": rid, "alias": js[0]["alias"] if js else None, "task_id": m["task_id"], "category": m["category"], "tier": m["tier"],
            "model": m["model"], "family": m["model_family"], "seed": m["seed"], "llm": llm, "human": hum, "combined": comb,
            "n_llm_judges": len(llm_by_run.get(rid, [])), "n_human": len(hum_by_run.get(rid, [])),
            "acceptable_llm": mean([1.0 if j["acceptable"] else 0.0 for j in llm_by_run.get(rid, [])]),
            "same_family_judges": [j["judge"] for j in llm_by_run.get(rid, []) if j["same_family"]], "injection_flag": injection,
            "checks": c["summary"], "gate": c["site_works_gate"], "integrity_counts": c["results"].get("integrity", {}).get("counts"),
            "qa_pass_rate": c["results"].get("product_qa", {}).get("pass_rate"), "cost_usd": m["cost_usd"], "steps": m["steps"],
            "tokens": m["usage"]["input_tokens"] + m["usage"]["output_tokens"], "wall_clock_s": m["wall_clock_s"], "stop_reason": m["stop_reason"],
            "sim_revenue": round(sum(w["revenue"] for w in weeks), 2), "sim_conversions": sum(w["conversions"] for w in weeks),
            "sim_spend": round(sum(w["spend"] for w in weeks), 2), "weekly_conversions": [w["conversions"] for w in weeks],
        })

    # pairwise -> Bradley-Terry / Elo over models (overall dimension), LLM and human separately
    model_of = {r["run_id"]: r["model"] for r in run_rows}

    def comps(rows, key="winners"):
        out = []
        for p in rows:
            w = p[key]["overall"]
            a, b = model_of.get(p["a"]), model_of.get(p["b"])
            if not a or not b:
                continue
            out.append((a, b, 1.0 if w == p["a"] else 0.0 if w == p["b"] else 0.5))
        return out

    llm_c, hum_c = comps(pair_rows), comps(human_pair)
    elo = {"llm": elo_from_bt(bradley_terry(llm_c)) if llm_c else {}, "human": elo_from_bt(bradley_terry(hum_c)) if hum_c else {}}
    elo_ci = bt_bootstrap(llm_c, reps=300) if len(llm_c) >= 4 else {}

    models = []
    for mm in meta["models"]:
        name = mm["name"]
        rows = [r for r in run_rows if r["model"] == name]
        if not rows:
            continue

        def ci(source: str, dim: str = "overall"):
            by_task = defaultdict(list)
            for r in rows:
                if r[source][dim] is not None:
                    by_task[r["task_id"]].append(r[source][dim])
            pt, lo, hi = hier_bootstrap(by_task, reps=reps)
            return {"mean": pt, "lo": lo, "hi": hi, "n": sum(len(v) for v in by_task.values())}

        by_task_gate = defaultdict(list)
        for r in rows:
            by_task_gate[r["task_id"]].append(r["gate"])
        cost = mean([r["cost_usd"] for r in rows])
        overall = ci("combined")
        models.append({
            "model": name, "family": rows[0]["family"], "requested": mm.get("requested"), "fallback_used": mm.get("fallback_used"),
            "n_runs": len(rows), "overall": {"combined": overall, "llm": ci("llm"), "human": ci("human")},
            "dims": {d: {"llm": mean([r["llm"][d] for r in rows]), "human": mean([r["human"][d] for r in rows]), "combined": ci("combined", d)} for d in dims},
            "by_category": {cat: mean([r["combined"]["overall"] for r in rows if r["category"] == cat]) for cat in sorted({r["category"] for r in rows})},
            "by_tier": {str(t): mean([r["combined"]["overall"] for r in rows if r["tier"] == t]) for t in sorted({r["tier"] for r in rows})},
            "worst_seed_overall": min((r["combined"]["overall"] for r in rows if r["combined"]["overall"] is not None), default=None),
            "seed_spread": mean([max(v) - min(v) for v in _by_task(rows).values() if len(v) > 1]),
            "pass_k_site_works": mean([1.0 if all(v) else 0.0 for v in by_task_gate.values()]),
            "acceptable_rate_llm": mean([r["acceptable_llm"] for r in rows]),
            "integrity_high_flags_per_run": mean([(r["integrity_counts"] or {}).get("high", 0) for r in rows]),
            "cost_usd_mean": cost, "tokens_mean": mean([r["tokens"] for r in rows]), "steps_mean": mean([r["steps"] for r in rows]),
            "score_per_dollar": (overall["mean"] / cost) if cost and overall["mean"] else None,
            "elo_llm": elo["llm"].get(name), "elo_llm_ci": elo_ci.get(name), "elo_human": elo["human"].get(name),
            "sim_revenue_mean": mean([r["sim_revenue"] for r in rows]),
        })
    models.sort(key=lambda m: -(m["overall"]["combined"]["mean"] or 0))
    for i, m in enumerate(models):
        lo = m["overall"]["combined"]["lo"]
        better = sum(1 for o in models if o is not m and (o["overall"]["combined"]["lo"] or 0) > (m["overall"]["combined"]["hi"] or 0))
        tied = [o["model"] for o in models if o is not m and (o["overall"]["combined"]["hi"] or 0) >= (lo or 0) and (o["overall"]["combined"]["lo"] or 0) <= (m["overall"]["combined"]["hi"] or 0)]
        m["rank"], m["rank_best"], m["statistically_tied_with"] = i + 1, better + 1, tied

    # agreement
    agreement = {"llm_vs_human": {}, "human_alpha": {}, "llm_judge_alpha": {}}
    for d in dims:
        pairs = [(r["llm"][d], r["human"][d]) for r in run_rows if r["llm"][d] is not None and r["human"][d] is not None]
        if pairs:
            l, h = [p[0] for p in pairs], [p[1] for p in pairs]
            agreement["llm_vs_human"][d] = {"n": len(pairs), "spearman": spearman(l, h), "mae": mean([abs(a - b) for a, b in pairs]),
                                            "within_1": mean([1.0 if abs(a - b) <= 1 else 0.0 for a, b in pairs])}
        hu = {rid: [h["scores"][d] for h in hs if h["scores"].get(d) is not None] for rid, hs in hum_by_run.items()}
        agreement["human_alpha"][d] = krippendorff_alpha(hu)
        lu = {rid: [j["scores"][d] for j in js] for rid, js in llm_by_run.items()}
        agreement["llm_judge_alpha"][d] = krippendorff_alpha(lu)
    hp = {(p["a"], p["b"]): p["winners"]["overall"] for p in human_pair}
    lp = [(hp[(p["a"], p["b"])], p["winners"]["overall"]) for p in pair_rows if (p["a"], p["b"]) in hp]
    agreement["pairwise_llm_human"] = {"n": len(lp), "agree": mean([1.0 if a == b else 0.0 for a, b in lp])} if lp else {"n": 0, "agree": None}

    results = {
        "round": meta["round"], "title": meta.get("title"), "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "rubric": RUBRIC_VERSION,
        "harness_version": meta.get("harness_version"), "prompt_version": meta.get("prompt_version"),
        "judges": sorted({r["judge"] for r in abs_rows}), "weights": {"human": w_h, "llm": w_l}, "dims": dims,
        "tasks": sorted({r["task_id"] for r in run_rows}), "seeds": meta.get("seeds"), "models": models, "runs": run_rows,
        "pairwise": {"n": len(pair_rows), "n_human": len(human_pair), "position_consistency": mean([p["position_consistency"] for p in pair_rows])},
        "agreement": agreement, "human_coverage": {"runs_with_human": sum(1 for r in run_rows if r["n_human"]), "total_runs": len(run_rows),
                                                   "graders": sorted({h["grader"] for h in human_abs}),
                                                   "synthetic_only": bool(human_abs) and all(h.get("synthetic") for h in human_abs)},
        "uses_mock_models": any(m["family"].startswith("mock") for m in models),
    }
    (round_dir / "results.json").write_text(json.dumps(results, indent=2))
    return results


def _by_task(rows):
    out = defaultdict(list)
    for r in rows:
        if r["combined"]["overall"] is not None:
            out[r["task_id"]].append(r["combined"]["overall"])
    return out
