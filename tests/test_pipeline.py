"""End to end on mocks: round -> judges -> grading app -> aggregation -> report -> site."""

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from shingle.config import ROOT, get_settings

pytestmark = pytest.mark.browser


@pytest.fixture(scope="module")
def round_dir():
    from shingle.app.db import populate_round
    from shingle.grading.aggregate import aggregate, grade_round
    from shingle.harness.runner import run_round

    rd = run_round(ROOT / "evals" / "ci.yaml", echo=lambda *_: None)
    grade_round(rd, ["mock-judge-a", "mock-judge-b"], echo=lambda *_: None)
    aggregate(rd)
    assert populate_round(rd) > 0
    return rd


@pytest.fixture(scope="module")
def client(round_dir):
    from shingle.app.main import app

    return TestClient(app, follow_redirects=False)


def login(c, user, pw):
    r = c.post("/login", data={"username": user, "password": pw, "next": "/"})
    assert r.status_code == 303, r.text


def test_round_outputs(round_dir):
    runs = [d for d in round_dir.iterdir() if (d / "bundle" / "checks.json").exists()]
    assert len(runs) == 2
    res = json.loads((round_dir / "results.json").read_text())
    names = [m["model"] for m in res["models"]]
    assert names[0] == "mock-diligent", "the honest baseline should beat the corner-cutter"
    assert res["pairwise"]["n"] == 2


def test_blind_grading_flow(client, round_dir):
    login(client, "grader1", "grader")
    q = client.get("/")
    assert q.status_code == 200 and not re.search(r"mock-(diligent|hasty)", q.text)
    from shingle.app.db import Assignment, Grader, Item, session
    from sqlalchemy import select

    with session() as s:
        g = s.scalar(select(Grader).where(Grader.username == "grader1"))
        rows = s.execute(select(Assignment, Item).join(Item, Assignment.item_id == Item.id).where(Assignment.grader_id == g.id)).all()
    absolute = next(a for a, it in rows if it.kind == "absolute" and not it.is_attention and not it.is_gold)
    pair = next((a for a, it in rows if it.kind == "pairwise"), None)
    page = client.get(f"/grade/{absolute.id}")
    assert page.status_code == 200 and not re.search(r"mock-(diligent|hasty)", page.text)
    alias = re.search(r"business (B-[0-9A-F]{6})", page.text).group(1)
    # frozen site on its own origin via Host routing, scrubbed
    site = client.get("/", headers={"host": f"{alias.lower()}.localhost:8000"})
    assert site.status_code == 200 and "<html" in site.text.lower()
    from shingle.grading.rubric import dim_ids

    form = {f"score_{d}": "5" for d in dim_ids()} | {"acceptable": "yes", "rationale": "Working checkout and honest copy; targeting fits."}
    assert client.post(f"/grade/{absolute.id}", data=form).status_code == 303
    bad = {f"score_{d}": "5" for d in dim_ids()} | {"acceptable": "yes", "rationale": "short"}
    assert client.post(f"/grade/{absolute.id}", data=bad).status_code == 400
    if pair:
        assert client.get(f"/grade/{pair.id}").status_code == 200
        pf = {f"win_{d}": "left" for d in dim_ids()} | {"rationale": "Left business works end to end; right does not."}
        assert client.post(f"/grade/{pair.id}", data=pf).status_code == 303


def test_attention_check_and_admin(client):
    from shingle.app.db import Assignment, Grader, Item, session
    from shingle.grading.rubric import dim_ids
    from sqlalchemy import select

    client.get("/logout")
    login(client, "grader2", "grader")
    with session() as s:
        g = s.scalar(select(Grader).where(Grader.username == "grader2"))
        a = s.execute(select(Assignment, Item).join(Item, Assignment.item_id == Item.id).where(Assignment.grader_id == g.id, Item.is_attention.is_(True))).first()[0]
    form = {f"score_{d}": "4" for d in dim_ids()} | {"acceptable": "no", "rationale": "Ignored the attention instruction on purpose."}
    assert client.post(f"/grade/{a.id}", data=form).status_code == 303
    client.get("/logout")
    assert client.get("/admin").status_code == 303  # needs login
    login(client, "admin", "admin")
    adm = client.get("/admin")
    assert adm.status_code == 200 and "Agreement" in adm.text
    exp = client.get("/admin/export.json").json()
    assert any(r["attention"] and r["attention_passed"] is False for r in exp)
    assert client.get("/dashboard").status_code == 200
    run_id = exp[0]["run_a"]
    assert client.get(f"/dashboard/run/{run_id}").status_code == 200
    assert client.get(f"/dashboard/run/{run_id}/trajectory").status_code == 200
    assert client.post("/api/contact", json={"email": "lab@x.test", "message": "hi"}).json()["ok"]


def test_human_aggregation_report_and_site(client, round_dir, tmp_path):
    from shingle.app.db import export_human_judgments
    from shingle.grading.aggregate import aggregate
    from shingle.report import generate_report
    from shingle.website.build import PAGES, build_site

    ha, hp = export_human_judgments(round_dir.name)
    assert all(not h["excluded"] for h in ha if not h["is_attention"])
    res = aggregate(round_dir, ha, hp)
    assert res["human_coverage"]["runs_with_human"] >= 1
    out = generate_report(round_dir)
    assert "Leaderboard" in (out / "report.md").read_text()
    site = build_site(round_dir.name, tmp_path / "site")
    for p in PAGES:
        assert (site / f"{p}.html").exists()
    assert (site / "data" / "results.json").exists()
    assert len(list((site / "showcase").glob("*.html"))) == 2
    assert get_settings().data_dir == Path(get_settings().data_dir)
