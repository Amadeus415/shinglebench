"""Task suite: schema, loading, validation."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .schema import SCHEMA_VERSION, Category, Task

ROOT = Path(__file__).resolve().parents[3]
TASKS_DIR = ROOT / "tasks"


def load_task(path: Path) -> Task:
    return Task.model_validate(yaml.safe_load(path.read_text()))


def load_tasks(split: str | None = None, include_heldout: bool = True) -> dict[str, Task]:
    """Load every task under tasks/<split>/. Held-out tasks may be absent in public clones."""
    splits = [split] if split else ["dev", "heldout"]
    if not include_heldout:
        splits = [s for s in splits if s != "heldout"]
    out: dict[str, Task] = {}
    for s in splits:
        for p in sorted((TASKS_DIR / s).glob("*.yaml")):
            t = load_task(p)
            if t.split != s:
                raise ValueError(f"{p}: split field '{t.split}' does not match directory '{s}'")
            if t.id in out:
                raise ValueError(f"duplicate task id {t.id}")
            if p.stem != t.id:
                raise ValueError(f"{p}: filename must equal task id '{t.id}'")
            out[t.id] = t
    return out


def get_task(task_id: str) -> Task:
    tasks = load_tasks()
    if task_id not in tasks:
        raise KeyError(f"unknown task '{task_id}'")
    return tasks[task_id]


def export_json_schema(path: Path) -> None:
    path.write_text(json.dumps(Task.model_json_schema(), indent=2))


__all__ = ["SCHEMA_VERSION", "Category", "Task", "load_task", "load_tasks", "get_task", "export_json_schema"]
