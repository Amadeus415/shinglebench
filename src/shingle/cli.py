"""`shingle` command line."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False, help="ShingleBench: can an AI start a business?")
tasks_app = typer.Typer(no_args_is_help=True, help="Inspect and validate the task suite.")
app.add_typer(tasks_app, name="tasks")


@tasks_app.command("validate")
def tasks_validate() -> None:
    """Validate every task file against the schema and print a coverage table."""
    from .tasks import TASKS_DIR, load_tasks

    tasks = load_tasks()
    typer.echo(f"{len(tasks)} tasks valid under {TASKS_DIR}")
    for split in ("dev", "heldout"):
        n = sum(1 for t in tasks.values() if t.split == split)
        typer.echo(f"  {split}: {n}")
    cats = Counter(t.category.value for t in tasks.values())
    tiers = Counter(t.tier for t in tasks.values())
    typer.echo("  categories: " + ", ".join(f"{k}={v}" for k, v in sorted(cats.items())))
    typer.echo("  tiers: " + ", ".join(f"tier{k}={v}" for k, v in sorted(tiers.items())))


@tasks_app.command("show")
def tasks_show(task_id: str) -> None:
    """Print a task exactly as the model under test sees it."""
    from .harness.prompts import task_message
    from .tasks import get_task

    typer.echo(task_message(get_task(task_id)))


@tasks_app.command("schema")
def tasks_schema(out: Path = Path("tasks/task.schema.json")) -> None:
    """Export the JSON Schema for task files."""
    from .tasks import export_json_schema

    export_json_schema(out)
    typer.echo(f"wrote {out}")


@app.command("run")
def run(config: Path = typer.Argument(Path("evals/demo.yaml")), force: bool = False, concurrency: int = typer.Option(None)) -> None:
    """Run an evaluation round (models × tasks × seeds): episode, bundle and automated checks for each run."""
    from .harness.runner import run_round

    out = run_round(config, force=force, concurrency=concurrency, echo=typer.echo)
    typer.echo(f"done: {out}")


@app.command("grade")
def grade(round_name: str = typer.Argument("demo-r1"), judges: str = typer.Option(None, help="comma-separated judge models"),
          force: bool = False, no_app: bool = typer.Option(False, help="skip populating the human grading app")) -> None:
    """Score every run with LLM judges (absolute + position-swapped pairwise), queue human grading, aggregate results."""
    import json

    from .config import get_settings
    from .grading.aggregate import aggregate, grade_round

    s = get_settings()
    rd = s.runs_dir / round_name
    meta = json.loads((rd / "round.json").read_text())
    js = [j.strip() for j in judges.split(",")] if judges else (meta.get("judges") or s.judge_models)
    grade_round(rd, js, force=force, echo=typer.echo)
    human_abs, human_pair = [], []
    if not no_app:
        from .app.db import export_human_judgments, populate_round

        populate_round(rd)
        human_abs, human_pair = export_human_judgments(round_name)
    res = aggregate(rd, human_abs, human_pair)
    for m in res["models"]:
        o = m["overall"]["combined"]
        typer.echo(f"  #{m['rank']} {m['model']}: overall {o['mean']:.2f} [{o['lo']:.2f}, {o['hi']:.2f}]  elo={m['elo_llm'] and round(m['elo_llm'])}")
    typer.echo(f"wrote {rd / 'results.json'}")


@app.command("report")
def report(round_name: str = typer.Argument("demo-r1")) -> None:
    """Generate the round report (markdown + HTML) from results.json."""
    from .config import get_settings
    from .report import generate_report

    out = generate_report(get_settings().runs_dir / round_name)
    typer.echo(f"wrote {out / 'report.md'} and {out / 'report.html'}")


@app.command("site")
def site(round_name: str = typer.Argument("demo-r1"), out: Path = typer.Option(None)) -> None:
    """Build the static company website from a round's results."""
    from .website.build import build_site

    dest = build_site(round_name, out)
    typer.echo(f"built {dest} (serve with: python -m http.server -d {dest} 8080)")


@app.command("serve")
def serve(host: str = "0.0.0.0", port: int = 8000) -> None:
    """Start the grading app + dashboard (frozen sites at http://<alias>.localhost:<port>/)."""
    import uvicorn

    uvicorn.run("shingle.app.main:app", host=host, port=port, log_level="info")


@app.command("demo")
def demo(config: Path = typer.Argument(Path("evals/demo.yaml")), fresh: bool = typer.Option(False, help="delete the round and its grading items first"),
         demo_graders: bool = typer.Option(True, help="fill the labeled synthetic demo-grader queues so human-side views have data")) -> None:
    """Everything end to end: run the round, judge it, populate grading, write the report and build the company site."""
    import shutil

    import yaml

    from .app.db import export_human_judgments, populate_round, reset_round, simulate_demo_graders
    from .config import get_settings
    from .grading.aggregate import aggregate, grade_round
    from .harness.runner import run_round
    from .report import generate_report
    from .website.build import build_site

    s = get_settings()
    rname = yaml.safe_load(config.read_text())["round"]
    rd = s.runs_dir / rname
    if fresh:
        shutil.rmtree(rd, ignore_errors=True)
        reset_round(rname)
    run_round(config, echo=typer.echo)
    meta = json.loads((rd / "round.json").read_text())
    grade_round(rd, meta.get("judges") or s.judge_models, echo=typer.echo)
    aggregate(rd)  # LLM-only results first, so gold items can use judge consensus
    populate_round(rd)
    if demo_graders:
        typer.echo(f"scripted demo-grader judgments: {simulate_demo_graders(rd)} (synthetic, labeled)")
    res = aggregate(rd, *export_human_judgments(rname))
    generate_report(rd)
    site = build_site(rname)
    for m in res["models"]:
        o = m["overall"]["combined"]
        typer.echo(f"  #{m['rank']} {m['model']}: {o['mean']:.2f} [{o['lo']:.2f}, {o['hi']:.2f}]")
    typer.echo(f"report: {rd / 'report' / 'report.html'}\nsite:   {site}\napp:    shingle serve  ->  {s.app_url} (admin/admin, grader1/grader)")


@app.command("up")
def up(config: Path = typer.Argument(Path("evals/demo.yaml")), port: int = 8000, site_port: int = 8080, fresh: bool = False) -> None:
    """Run the demo if it hasn't run yet, then serve the grading app (:8000) and the company site (:8080)."""
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    import uvicorn
    import yaml

    from .config import ROOT, get_settings

    rname = yaml.safe_load(config.read_text())["round"]
    if fresh or not (get_settings().runs_dir / rname / "results.json").exists() or not (ROOT / "site_build" / "index.html").exists():
        demo(config, fresh=fresh, demo_graders=True)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT / "site_build"))
    handler.log_message = lambda *a, **k: None
    site_srv = ThreadingHTTPServer(("0.0.0.0", site_port), handler)
    threading.Thread(target=site_srv.serve_forever, daemon=True).start()
    typer.echo(f"company site: http://localhost:{site_port}\ngrading app:  http://localhost:{port}  (admin/admin, grader1/grader)")
    uvicorn.run("shingle.app.main:app", host="0.0.0.0", port=port, log_level="warning")


@app.command("export")
def export(run_dir: Path, out: Path = typer.Option(None)) -> None:
    """Zip a run bundle for sharing."""
    from .bundle import export_bundle

    dest = export_bundle(run_dir / "bundle", out or run_dir.with_suffix(".zip"))
    typer.echo(f"wrote {dest}")


@app.command("episode")
def episode(task: str = typer.Option(..., help="task id"), model: str = typer.Option("mock-diligent"), seed: int = 1,
            out: Path = typer.Option(None, help="run directory (default var/runs/adhoc/<run_id>)")) -> None:
    """Run a single episode (no bundle/checks). Useful for debugging a model or task."""
    import json

    from .config import get_settings
    from .harness.agent import Episode
    from .harness.providers import get_model
    from .tasks import get_task

    s = get_settings()
    run_dir = out or s.runs_dir / "adhoc" / f"{task}__{model}__s{seed}"
    res = Episode(run_dir, get_task(task), get_model(model), seed, s).run()
    res["world"].close()
    typer.echo(json.dumps(res["manifest"], indent=2))


if __name__ == "__main__":
    app()
