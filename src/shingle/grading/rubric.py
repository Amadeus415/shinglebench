"""Versioned rubric loading and the integrity cap."""

from __future__ import annotations

from functools import lru_cache

import yaml

from ..config import ROOT

RUBRIC_VERSION = "rubric-v1"


@lru_cache
def rubric(version: str = RUBRIC_VERSION) -> dict:
    return yaml.safe_load((ROOT / "rubric" / f"{version}.yaml").read_text())


def dimensions(version: str = RUBRIC_VERSION) -> list[dict]:
    return rubric(version)["dimensions"]


def dim_ids(version: str = RUBRIC_VERSION) -> list[str]:
    return [d["id"] for d in dimensions(version)]


def apply_caps(scores: dict[str, float], version: str = RUBRIC_VERSION) -> tuple[dict[str, float], list[str]]:
    out, notes = dict(scores), []
    for cap in rubric(version).get("caps", []):
        w, t = cap["when"], cap["then"]
        if w["dimension"] in out and out[w["dimension"]] <= w["at_most"] and out.get(t["dimension"], 0) > t["at_most"]:
            out[t["dimension"]] = t["at_most"]
            notes.append(f"{t['dimension']} capped at {t['at_most']}: {cap['why']}")
    return out, notes


def rubric_text(version: str = RUBRIC_VERSION) -> str:
    r = rubric(version)
    lines = [r["instructions"].strip(), ""]
    for d in r["dimensions"]:
        lines.append(f"## {d['id']}: {d['name']}\n{d['question']}")
        lines += [f"  {k}: {v}" for k, v in d["anchors"].items()]
        lines.append("")
    for c in r.get("caps", []):
        lines.append(f"CAP: if {c['when']['dimension']} <= {c['when']['at_most']} then {c['then']['dimension']} <= {c['then']['at_most']} ({c['why']})")
    lines.append(f"\nAlso answer: {r['acceptable_question']}")
    return "\n".join(lines)
