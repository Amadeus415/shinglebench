"""Evaluation rounds: models × tasks × seeds, each episode in its own process.

A round config (evals/*.yaml):
  round: demo-r1
  models: [{use: claude-opus-5-5, fallback: mock-diligent}, mock-hasty]
  tasks: [rent-split-calculator, ...]
  seeds: [1, 2]          # default 3 seeds: [1, 2, 3]
  concurrency: 3
Runs are resumable: finished runs are skipped, interrupted ones resume from their checkpoint.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import yaml

from ..config import HARNESS_VERSION, PROMPT_VERSION, get_settings
from .providers import get_model, has_credentials


def resolve_models(entries: list) -> list[dict]:
    out = []
    for e in entries:
        e = {"use": e} if isinstance(e, str) else dict(e)
        cfg = get_model(e["use"])
        if has_credentials(cfg):
            out.append({"name": cfg.name, "requested": e["use"], "fallback_used": False})
        elif e.get("fallback"):
            out.append({"name": get_model(e["fallback"]).name, "requested": e["use"], "fallback_used": True})
        else:
            raise SystemExit(f"model {e['use']} needs {cfg.api_key_env} (or give it a `fallback:` in the eval config)")
    names = [m["name"] for m in out]
    if len(set(names)) != len(names):
        raise SystemExit(f"two model entries resolve to the same config: {names}")
    return out


def run_id(task: str, model: str, seed: int) -> str:
    return f"{task}__{model}__s{seed}"


def run_one(round_dir: str, task_id: str, model_name: str, seed: int, force: bool = False) -> dict:
    """Episode -> bundle -> checks. Executed in a worker process."""
    from ..bundle import build_bundle
    from ..checks import run_checks
    from ..tasks import get_task
    from .agent import Episode

    rd = Path(round_dir) / run_id(task_id, model_name, seed)
    done = rd / "bundle" / "checks.json"
    if done.exists() and not force:
        return {"run_id": rd.name, "status": "cached"}
    if force and rd.exists():
        import shutil

        shutil.rmtree(rd)
    t0 = time.time()
    s = get_settings()
    task = get_task(task_id)
    try:
        res = Episode(rd, task, get_model(model_name), seed, s).run()
        world = res["world"]
        try:
            bundle = build_bundle(rd, world)
        finally:
            world.close()
        checks = run_checks(bundle, task, s.qa_model)
        return {"run_id": rd.name, "status": "complete", "stop_reason": res["manifest"]["stop_reason"], "steps": res["manifest"]["steps"],
                "cost_usd": res["manifest"]["cost_usd"], "checks": checks["counts"], "gate": checks["site_works_gate"], "seconds": round(time.time() - t0, 1)}
    except Exception as e:
        (rd / "error.txt").parent.mkdir(parents=True, exist_ok=True)
        (rd / "error.txt").write_text(traceback.format_exc())
        return {"run_id": rd.name, "status": "error", "error": f"{type(e).__name__}: {e}"}


def run_round(config_path: Path, force: bool = False, concurrency: int | None = None, echo=print) -> Path:
    cfg = yaml.safe_load(config_path.read_text())
    s = get_settings()
    round_name = cfg["round"]
    round_dir = s.runs_dir / round_name
    round_dir.mkdir(parents=True, exist_ok=True)
    models = resolve_models(cfg["models"])
    seeds = cfg.get("seeds") or [1, 2, 3]
    jobs = [(t, m["name"], sd) for t in cfg["tasks"] for m in models for sd in seeds]
    meta = {"round": round_name, "title": cfg.get("title", round_name), "config": str(config_path), "models": models, "tasks": cfg["tasks"],
            "seeds": seeds, "harness_version": HARNESS_VERSION, "prompt_version": PROMPT_VERSION, "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "judges": cfg.get("judges") or s.judge_models, "runs": {}}
    meta_path = round_dir / "round.json"
    if meta_path.exists():
        meta["runs"] = json.loads(meta_path.read_text()).get("runs", {})
    for m in models:
        if m["fallback_used"]:
            echo(f"note: {m['requested']} has no API key; using {m['name']} instead")
    echo(f"round {round_name}: {len(jobs)} runs ({len(cfg['tasks'])} tasks × {len(models)} models × {len(seeds)} seeds)")
    workers = concurrency or cfg.get("concurrency", 3)
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as ex:
        futs = {ex.submit(run_one, str(round_dir), t, m, sd, force): (t, m, sd) for t, m, sd in jobs}
        for f in as_completed(futs):
            r = f.result()
            if r["status"] != "cached" or r["run_id"] not in meta["runs"]:
                meta["runs"][r["run_id"]] = r
            echo(f"  {r['status']:9s} {r['run_id']}" + (f"  checks={r.get('checks')} gate={r.get('gate')} {r.get('seconds')}s" if r["status"] == "complete" else f"  {r.get('error', '')}"))
            meta_path.write_text(json.dumps(meta, indent=2))
    meta["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta_path.write_text(json.dumps(meta, indent=2))
    return round_dir
