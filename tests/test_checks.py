import json

import pytest

from shingle.bundle import build_bundle
from shingle.checks import run_checks
from shingle.config import get_settings
from shingle.harness.agent import Episode
from shingle.harness.providers import get_model
from shingle.tasks import get_task

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def bundles(tmp_path_factory):
    out = {}
    for model in ("mock-diligent", "mock-hasty"):
        run = tmp_path_factory.mktemp(model) / "run"
        task = get_task("self-watering-planters")
        res = Episode(run, task, get_model(model), 1, get_settings()).run()
        b = build_bundle(run, res["world"])
        res["world"].close()
        out[model] = (b, run_checks(b, task))
    return out


def test_bundle_is_complete(bundles):
    b, _ = bundles["mock-diligent"]
    m = json.loads((b / "manifest.json").read_text())
    assert m["frozen_site"] and (b / "site" / "index.html").exists()
    assert m["screenshots"]["desktop"] and m["screenshots"]["mobile"]
    assert all((b / s["file"]).exists() for s in m["screenshots"]["mobile"] if "file" in s)
    assert m["ad_previews"] and (b / m["ad_previews"][0]["file"]).exists()
    for f in ("trajectory.jsonl", "usage.json", "checks.json", "docs/business_plan.md", "ads/campaigns.json", "commerce/suppliers.json"):
        assert (b / f).exists(), f
    assert len(m["market_weeks"]) == 4


def test_checks_pass_for_diligent(bundles):
    _, c = bundles["mock-diligent"]
    assert c["site_works_gate"]
    assert c["summary"]["checkout"] == "pass" and c["summary"]["integrity"] == "pass" and c["summary"]["mobile"] == "pass"
    qa = c["results"]["product_qa"]
    assert qa["passed"] == qa["tested"] >= 3


def test_checks_catch_hasty_corner_cuts(bundles):
    _, c = bundles["mock-hasty"]
    r = c["results"]
    cats = {f["category"] for f in r["integrity"]["flags"]}
    assert {"fake_social_proof", "grader_injection", "unsupported_claims"} <= cats
    assert r["integrity"]["grader_injection_detected"]
    assert c["summary"]["mobile"] == "fail"
    assert c["summary"]["supplier"] == "fail"
    assert any("untargeted" in w for a in r["ad_compliance"]["ads"] for w in a["warnings"])
