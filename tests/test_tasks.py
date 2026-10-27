from collections import Counter

import pytest

from shingle.config import ROOT
from shingle.sandbox.ads import interests
from shingle.tasks import load_tasks
from shingle.tasks.schema import Category

# The public copy of the repo ships without tasks/heldout/ (see scripts/export_public.sh).
needs_heldout = pytest.mark.skipif(not any((ROOT / "tasks" / "heldout").glob("*.yaml")), reason="held-out tasks are private")


def test_dev_set_covers_every_category():
    dev = [t for t in load_tasks().values() if t.split == "dev"]
    assert {t.category for t in dev} == set(Category)


@needs_heldout
def test_suite_size_and_coverage():
    tasks = load_tasks()
    assert len(tasks) >= 24
    cats = Counter(t.category for t in tasks.values())
    assert set(cats) == set(Category)
    for c in Category:
        tiers = {t.tier for t in tasks.values() if t.category == c}
        assert {1, 3} <= tiers, f"{c} needs tier 1 and tier 3 tasks"
    splits = Counter(t.split for t in tasks.values())
    assert splits["dev"] >= 3 and splits["heldout"] >= 6


@needs_heldout
def test_heldout_canaries_unique():
    held = [t for t in load_tasks().values() if t.split == "heldout"]
    canaries = [t.canary for t in held]
    assert all(c and c.startswith("shinglebench-canary:") for c in canaries)
    assert len(set(canaries)) == len(canaries)


def test_relevant_interests_exist():
    known = interests()
    for t in load_tasks().values():
        bad = [i for i in t.sim.relevant_interests if i not in known]
        assert not bad, f"{t.id}: unknown interests {bad}"


def test_facts_block_hides_grader_notes():
    for t in load_tasks().values():
        fb = t.facts_block()
        for note in t.grader_notes.great_looks_like[:1] + t.grader_notes.common_failures[:1]:
            assert note not in fb
        assert "reference_price" not in fb
