"""Round report (markdown + HTML) generated from results.json and the run bundles."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from pathlib import Path

import markdown as md

from ..grading.rubric import dimensions
from ..tasks import get_task
from ..viz import VIZ_CSS, ci_chart


def _f(v, nd=2, dash="–"):
    return dash if v is None else f"{v:.{nd}f}"


def failure_modes(round_dir: Path, results: dict) -> dict:
    checks, flags, qa = Counter(), Counter(), Counter()
    for r in results["runs"]:
        b = round_dir / r["run_id"] / "bundle"
        c = json.loads((b / "checks.json").read_text())
        for k, v in c["summary"].items():
            if v == "fail":
                checks[k] += 1
        for f in c["results"].get("integrity", {}).get("flags", []):
            if f["severity"] in ("high", "medium"):
                flags[f["category"]] += 1
        for q in c["results"].get("product_qa", {}).get("criteria", []):
            if q["result"] == "fail":
                qa[f"{r['task_id']}: {q['id']}"] += 1
    return {"checks": checks.most_common(), "flags": flags.most_common(), "qa": qa.most_common(8)}


def generate_report(round_dir: Path) -> Path:
    res = json.loads((round_dir / "results.json").read_text())
    out = round_dir / "report"
    if out.exists():
        shutil.rmtree(out)
    (out / "assets").mkdir(parents=True)
    dims = dimensions()
    fm = failure_modes(round_dir, res)
    runs = sorted([r for r in res["runs"] if r["combined"]["overall"] is not None], key=lambda r: -r["combined"]["overall"])
    examples = []
    for tag, r in (("Strongest run", runs[0] if runs else None), ("Weakest run", runs[-1] if runs else None)):
        if not r:
            continue
        b = round_dir / r["run_id"] / "bundle"
        m = json.loads((b / "manifest.json").read_text())
        shots = [s for s in m["screenshots"].get("desktop", []) if "file" in s][:1] + [s for s in m["screenshots"].get("mobile", []) if "file" in s][:1]
        files = []
        for s in shots + [{"file": p["file"]} for p in m.get("ad_previews", [])[:1]]:
            dst = f"assets/{r['run_id']}__{Path(s['file']).name}"
            shutil.copy(b / s["file"], out / dst)
            files.append(dst)
        js = [json.loads(line) for line in (round_dir / "judgments" / "llm_absolute.jsonl").read_text().splitlines()]
        rat = next((j["rationales"]["overall"] for j in js if j["run_id"] == r["run_id"]), "")
        examples.append({"tag": tag, "run": r, "files": files, "rationale": rat, "task": get_task(r["task_id"]).title})

    synthetic = res["human_coverage"].get("synthetic_only") or any(g.startswith("demo-grader") for g in res["human_coverage"].get("graders", []))
    lines = [f"# ShingleBench {res['title']}", "",
             f"*Round `{res['round']}` · generated {res['generated_at']} · rubric {res['rubric']} · harness {res['harness_version']} / prompt {res['prompt_version']}*", ""]
    if res.get("uses_mock_models"):
        lines += ["> **Demo round.** No model API keys were configured, so both entries are scripted mock agents (`mock-diligent`, an honest template founder; "
                  "`mock-hasty`, which cuts corners). The numbers demonstrate the pipeline end to end. They say nothing about real models.", ""]
    if synthetic:
        lines += ["> **Human grades** in this round include scripted demo grader accounts (synthetic, flagged in the data) used to exercise the agreement and QC tooling. "
                  "They are not human judgments.", ""]
    top = res["models"][0] if res["models"] else None
    lines += ["## Summary", ""]
    if top:
        o = top["overall"]["combined"]
        lines.append(f"- **{top['model']}** ranks first with an overall score of **{_f(o['mean'])}** (95% CI {_f(o['lo'])}–{_f(o['hi'])}) across {top['n_runs']} runs "
                     f"({len(res['tasks'])} tasks × {len(res['seeds'] or [])} seeds).")
    for m in res["models"][1:]:
        o = m["overall"]["combined"]
        tied = " (statistically tied with the leader)" if top and top["model"] in m["statistically_tied_with"] else ""
        lines.append(f"- {m['model']}: {_f(o['mean'])} (95% CI {_f(o['lo'])}–{_f(o['hi'])}){tied}.")
    lines += [f"- The site-works gate passed on every seed (pass^k) for {', '.join(f'{m['model']} {m['pass_k_site_works']:.0%}' for m in res['models'])} of tasks.",
              f"- Pairwise judgments: {res['pairwise']['n']} LLM comparisons, each run twice with positions swapped (mean position consistency {_f(res['pairwise']['position_consistency'])}).", ""]
    lines += ["## Leaderboard", "", "| # | Model | Overall | 95% CI | LLM | Human | Elo (pairwise) | pass^k | Worst seed | Cost/run |", "|---|---|---|---|---|---|---|---|---|---|"]
    for m in res["models"]:
        o = m["overall"]
        lines.append(f"| {m['rank']} | {m['model']} | {_f(o['combined']['mean'])} | {_f(o['combined']['lo'])}–{_f(o['combined']['hi'])} | {_f(o['llm']['mean'])} | "
                     f"{_f(o['human']['mean'])} | {round(m['elo_llm']) if m['elo_llm'] else '–'} | {m['pass_k_site_works']:.0%} | {_f(m['worst_seed_overall'], 1)} | ${_f(m['cost_usd_mean'])} |")
    lines += ["", "## Scores by dimension", "", "| Model | " + " | ".join(d["id"] for d in dims) + " |", "|---|" + "---|" * len(dims)]
    for m in res["models"]:
        lines.append(f"| {m['model']} | " + " | ".join(_f(m["dims"][d["id"]]["combined"]["mean"], 1) for d in dims) + " |")
    lines += ["", "## By category and tier", "", "| Model | " + " | ".join(res["models"][0]["by_category"]) + " | " + " | ".join(f"tier {t}" for t in res["models"][0]["by_tier"]) + " |",
              "|---|" + "---|" * (len(res["models"][0]["by_category"]) + len(res["models"][0]["by_tier"]))]
    for m in res["models"]:
        lines.append(f"| {m['model']} | " + " | ".join(_f(v) for v in m["by_category"].values()) + " | " + " | ".join(_f(v) for v in m["by_tier"].values()) + " |")
    lines += ["", "## Notable examples", ""]
    for ex in examples:
        r = ex["run"]
        lines += [f"### {ex['tag']}: {r['model']} on *{ex['task']}* (seed {r['seed']}, overall {_f(r['combined']['overall'])})", ""]
        lines += [f"![{ex['tag']} screenshot]({f})" for f in ex["files"]]
        lines += ["", f"Judge rationale: {ex['rationale']}", f"Checks failing: {', '.join(k for k, v in r['checks'].items() if v == 'fail') or 'none'} · simulated revenue {r['sim_revenue']:.0f} · alias {r['alias']}", ""]
    lines += ["## Failure modes", "", "Most frequent failing automated checks: " + (", ".join(f"{k} ({n})" for k, n in fm["checks"]) or "none") + ".",
              "", "Integrity flags (high/medium) by category: " + (", ".join(f"{k} ({n})" for k, n in fm["flags"]) or "none") + ".",
              "", "Product QA criteria most often failed: " + (", ".join(f"{k} ({n})" for k, n in fm["qa"]) or "none") + ".", ""]
    ag = res["agreement"]
    lines += ["## Grader agreement", "", "| Dimension | LLM↔human Spearman | MAE | Human α | LLM-judge α |", "|---|---|---|---|---|"]
    for d in dims:
        a = ag["llm_vs_human"].get(d["id"], {})
        lines.append(f"| {d['id']} | {_f(a.get('spearman'))} | {_f(a.get('mae'))} | {_f(ag['human_alpha'].get(d['id']))} | {_f(ag['llm_judge_alpha'].get(d['id']))} |")
    lines += ["", f"Pairwise LLM↔human agreement on the overall winner: {_f(ag['pairwise_llm_human']['agree'])} over {ag['pairwise_llm_human']['n']} shared comparisons.", ""]
    lines += ["## Methodology (short)", "",
              "Each run is one model, one brief and one seed in a network-less sandbox with simulated ad, payment and supplier services. "
              "The model builds and deploys a site, writes brand, plan and launch documents, and runs ads, then operates for several simulated weeks while a seeded customer panel browses the live site. "
              "At the end the site is frozen and automated checks run: load, links, audits, mobile, forms, test checkout, a product QA agent, ad compliance and integrity. "
              f"LLM judges ({', '.join(res['judges'])}) score each run on the rubric and compare runs pairwise with positions swapped. Humans grade blind in the grading app. "
              f"Combined score = {res['weights']['human']}×human + {res['weights']['llm']}×LLM where human grades exist. "
              "CIs come from a hierarchical bootstrap that resamples tasks, then seeds within each task. An integrity score of 2 or lower caps Overall at 3.", "",
              "## Limitations", "", "- Simulated market results are directional only and never part of the score.",
              "- Mock agents and mock judges are deterministic heuristics. Real-model rounds require API keys.",
              "- Screenshots are taken of the real site, so a model that writes its own name into the page can be identified from them. Text served to graders is scrubbed.", "",
              "## Reproduce", "", f"```\nshingle run evals/demo.yaml\nshingle grade {res['round']}\nshingle report {res['round']}\n```", ""]
    text = "\n".join(lines)
    (out / "report.md").write_text(text)
    body = md.markdown(text, extensions=["tables", "fenced_code"])
    chart = ci_chart([{"label": m["model"], "mean": m["overall"]["combined"]["mean"], "lo": m["overall"]["combined"]["lo"], "hi": m["overall"]["combined"]["hi"]} for m in res["models"]])
    body = body.replace("<h2>Leaderboard</h2>", "<h2>Leaderboard</h2>" + chart, 1)
    html_doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ShingleBench {res['title']}</title><style>
body{{font:16px/1.6 Georgia,"Iowan Old Style",serif;color:#16181d;background:#fcfcfb;max-width:860px;margin:40px auto;padding:0 20px}}
h1,h2,h3{{font-family:system-ui,sans-serif;letter-spacing:-.01em}}h1{{font-size:2rem}}table{{border-collapse:collapse;width:100%;font:14px system-ui,sans-serif;font-variant-numeric:tabular-nums;margin:8px 0 16px}}
th,td{{border-bottom:1px solid #e3e1dc;padding:6px 8px;text-align:left}}blockquote{{margin:0 0 12px;padding:10px 14px;background:#fff6dd;border-left:3px solid #e0b84a;font-family:system-ui,sans-serif;font-size:.95rem}}
img{{width:31%;height:360px;object-fit:cover;object-position:top;border:1px solid #e3e1dc;border-radius:6px;margin:4px 1% 4px 0;vertical-align:top}}code,pre{{font:13px ui-monospace,monospace;background:#f3f2ee;padding:2px 4px;border-radius:4px}}pre{{padding:10px}}
.small,.muted{{font:12px system-ui,sans-serif;color:#52514e}}{VIZ_CSS}</style></head><body>{body}</body></html>"""
    (out / "report.html").write_text(html_doc)
    return out

