import json

import pytest

from shingle.config import get_settings
from shingle.harness.agent import Episode
from shingle.harness.providers import get_model
from shingle.market.simulator import targeting_fit
from shingle.tasks import get_task

pytestmark = pytest.mark.browser


def _run(tmp_path, task="mobile-bike-repair-sunset", model="mock-diligent", seed=1):
    res = Episode(tmp_path / "run", get_task(task), get_model(model), seed, get_settings()).run()
    res["world"].close()
    return res["manifest"], tmp_path / "run"


def test_mock_episode_end_to_end(tmp_path):
    m, run = _run(tmp_path)
    assert m["status"] == "complete" and m["weeks_completed"] == 4
    events = [json.loads(line) for line in (run / "trajectory.jsonl").read_text().splitlines()]
    names = [e["name"] for e in events if e["type"] == "tool_call"]
    for needed in ("deploy_site", "ads_create_ad", "end_week", "finish"):
        assert needed in names
    assert all("ts" in e for e in events)
    weeks = sorted((run / "state" / "market").glob("week_*.json"))
    assert len(weeks) == 4
    w1 = json.loads(weeks[0].read_text())
    assert w1["simulated"] and w1["totals"]["clicks"] > 0
    assert any(v["converted"] for w in weeks for v in json.loads(w.read_text())["visits"]), "some simulated visitor should book"
    assert (run / "workspace" / "docs" / "business_plan.md").exists()


def test_episode_is_deterministic_and_resumable(tmp_path):
    m1, run1 = _run(tmp_path / "a", seed=3)
    m2, run2 = _run(tmp_path / "b", seed=3)
    t1 = [json.loads((run1 / "state/market" / f"week_{i}.json").read_text())["totals"] for i in (1, 2)]
    t2 = [json.loads((run2 / "state/market" / f"week_{i}.json").read_text())["totals"] for i in (1, 2)]
    assert [t["impressions"] for t in t1] == [t["impressions"] for t in t2]
    # resume: a finished checkpoint re-runs nothing and keeps the same step count
    res = Episode(run1, get_task("mobile-bike-repair-sunset"), get_model("mock-diligent"), 3, get_settings()).run()
    res["world"].close()
    assert res["manifest"]["steps"] == m1["steps"]


def test_targeting_fit_rewards_local_precision():
    task = get_task("mobile-bike-repair-sunset")
    local = targeting_fit(task, {"geo": {"locations": ["neighborhood:US:san-francisco:outer-sunset"], "radius_km": 2},
                                 "age_min": 25, "age_max": 60, "interests": ["cycling", "e-bikes"]})
    broad = targeting_fit(task, {"geo": {"countries": ["US"]}, "age_min": 18, "age_max": 65, "interests": []})
    assert local["precision"] > 5 * broad["precision"]
