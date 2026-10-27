"""Grading app + internal dashboard.

- Graders: blind queue, absolute and pairwise grading, time on task, flags.
- Frozen sites are served on their own origin: http://<alias>.localhost:<port>/ (Host-header routing),
  so absolute links and JS keep working exactly as deployed and grader cookies are never exposed.
- Admin: progress, QC (gold, attention, speed), agreement, flags, export, accounts, contacts.
- Dashboard (admin): leaderboard with CIs, breakdowns, run explorer, trajectories, reports.
"""

from __future__ import annotations

import csv
import html
import io
import json
import re
import statistics
from functools import lru_cache
from pathlib import Path

import markdown as md
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from starlette.middleware.sessions import SessionMiddleware

from ..config import get_settings
from ..grading.evidence import alias, change_log, scrub, week_timeline
from ..grading.rubric import dim_ids, dimensions
from ..grading.stats import krippendorff_alpha
from ..sandbox.hosting import frozen_platform
from ..tasks import get_task
from ..viz import VIZ_CSS, ci_chart, heat_cell, scatter
from .db import Assignment, Contact, Flag, Grader, Item, Judgment, check_pw, hash_pw, session, utcnow

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=str(HERE / "templates"))
templates.env.globals.update(ci_chart=ci_chart, heat_cell=heat_cell, scatter=scatter, VIZ_CSS=VIZ_CSS)
app = FastAPI(title="Shingle grading")
settings = get_settings()
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key, same_site="lax")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])
ALIAS_HOST = re.compile(r"^(b-[0-9a-f]{6})\.(?:sites\.)?localhost(?::\d+)?$", re.I)


# ------------------------------------------------------------------ bundle index
@lru_cache(maxsize=1)
def _index(stamp: float) -> dict[str, Path]:
    out = {}
    for rd in sorted(settings.runs_dir.glob("*")) if settings.runs_dir.exists() else []:
        for b in rd.glob("*/bundle"):
            out[alias(b.parent.name)] = b
    return out


def bundle_for(a: str) -> Path:
    stamp = max((p.stat().st_mtime for p in settings.runs_dir.glob("*")), default=0) if settings.runs_dir.exists() else 0
    b = _index(stamp).get(a.upper())
    if not b:
        raise HTTPException(404, "unknown bundle")
    return b


def run_bundle(run_id: str) -> Path:
    for rd in settings.runs_dir.glob("*"):
        if (rd / run_id / "bundle").exists():
            return rd / run_id / "bundle"
    raise HTTPException(404, "unknown run")


# ------------------------------------------------------------------ frozen sites by host
_platforms: dict[str, object] = {}


@app.middleware("http")
async def frozen_site_host(request: Request, call_next):
    m = ALIAS_HOST.match(request.headers.get("host", ""))
    if not m:
        return await call_next(request)
    a = m.group(1).upper()
    b = bundle_for(a)
    if a not in _platforms:
        _platforms[a] = frozen_platform(b, settings.data_dir / "grader_scratch" / f"{a}.json")
    body = await request.body()
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    r = _platforms[a].handle(request.method, path, dict(request.headers), body, source="grader")
    content = r.body
    ctype = r.headers.get("Content-Type", "")
    if ctype.startswith(("text/html", "text/css", "application/javascript", "text/javascript")):
        content = scrub(content.decode(errors="replace")).encode()  # blind: strip model fingerprints
    headers = {k: v for k, v in r.headers.items() if k.lower() != "content-length"}
    return Response(content, status_code=r.status, headers=headers)


# ------------------------------------------------------------------ auth
def user(request: Request) -> Grader | None:
    uid = request.session.get("uid")
    if not uid:
        return None
    with session() as s:
        return s.get(Grader, uid)


def need(request: Request, admin: bool = False) -> Grader:
    u = user(request)
    if not u or (admin and u.role != "admin"):
        raise HTTPException(303, headers={"Location": "/login?next=" + request.url.path})
    return u


@app.exception_handler(HTTPException)
async def redirects(request: Request, exc: HTTPException):
    if exc.status_code == 303:
        return RedirectResponse(exc.headers["Location"], 303)
    return PlainTextResponse(str(exc.detail), exc.status_code)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(request, "login.html", {"next": next, "error": None})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...), next: str = Form("/")):
    with session() as s:
        g = s.scalar(select(Grader).where(Grader.username == username))
    if not g or g.synthetic or not check_pw(password, g.password_hash):
        return templates.TemplateResponse(request, "login.html", {"next": next, "error": "Wrong username or password"}, status_code=401)
    request.session["uid"] = g.id
    return RedirectResponse(next if next.startswith("/") else "/", 303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)


@app.get("/healthz")
def healthz():
    return {"ok": True}


# ------------------------------------------------------------------ grader queue
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    u = need(request)
    with session() as s:
        rows = s.execute(select(Assignment, Item).join(Item, Assignment.item_id == Item.id).where(Assignment.grader_id == u.id)
                         .order_by(Assignment.status.desc(), Assignment.id)).all()
    pending = [(a, i) for a, i in rows if a.status == "pending"]
    done = [(a, i) for a, i in rows if a.status == "done"]
    return templates.TemplateResponse(request, "queue.html", {"u": u, "pending": pending, "done": done, "alias": alias})


@app.get("/next")
def next_item(request: Request):
    u = need(request)
    with session() as s:
        a = s.scalar(select(Assignment).where(Assignment.grader_id == u.id, Assignment.status == "pending").order_by(Assignment.id))
    return RedirectResponse(f"/grade/{a.id}" if a else "/", 303)


def evidence(run_id: str) -> dict:
    b = run_bundle(run_id)
    m = json.loads((b / "manifest.json").read_text())
    a = alias(run_id)
    checks = json.loads((b / "checks.json").read_text()) if (b / "checks.json").exists() else {}
    creatives = json.loads((b / "ads" / "creatives.json").read_text()) if (b / "ads" / "creatives.json").exists() else []
    docs = {}
    for d in ("brand", "business_plan", "launch_plan"):
        f = b / "docs" / f"{d}.md"
        if f.exists():
            docs[d] = md.markdown(html.escape(scrub(f.read_text())), extensions=["tables"])
    return {"alias": a, "manifest": m, "checks": checks, "creatives": creatives, "docs": docs, "weeks": week_timeline(b),
            "changes": change_log(b), "shots": m.get("screenshots", {}), "previews": {p["ad_id"]: p["file"] for p in m.get("ad_previews", [])}}


@app.get("/grade/{aid}", response_class=HTMLResponse)
def grade_page(request: Request, aid: int):
    u = need(request)
    with session() as s:
        a = s.get(Assignment, aid)
        if not a or a.grader_id != u.id:
            raise HTTPException(404, "not your assignment")
        it = s.get(Item, a.item_id)
        if a.started_at is None:
            a.started_at = utcnow()
            s.commit()
    task = get_task(it.task_id)
    host = request.url.hostname or "localhost"
    port = f":{request.url.port}" if request.url.port else ""
    site_base = lambda al: f"{request.url.scheme}://{al.lower()}.{host if host != '127.0.0.1' else 'localhost'}{port}/"  # noqa: E731
    ctx = {"u": u, "a": a, "it": it, "task": task, "dims": dimensions(), "site_base": site_base, "done": a.status == "done"}
    if it.kind == "absolute":
        ctx["ev"] = evidence(it.run_a)
        return templates.TemplateResponse(request, "grade_absolute.html", ctx)
    left, right = (it.run_a, it.run_b) if it.left_is_a else (it.run_b, it.run_a)
    ctx["left"], ctx["right"] = evidence(left), evidence(right)
    return templates.TemplateResponse(request, "grade_pairwise.html", ctx)


@app.post("/grade/{aid}")
async def grade_submit(request: Request, aid: int):
    u = need(request)
    form = await request.form()
    with session() as s:
        a = s.get(Assignment, aid)
        if not a or a.grader_id != u.id:
            raise HTTPException(404, "not your assignment")
        it = s.get(Item, a.item_id)
        rationale = str(form.get("rationale", "")).strip()
        if len(rationale) < 20:
            raise HTTPException(400, "A short rationale (20+ characters) is required.")
        flags = form.getlist("flags")
        j = Judgment(assignment_id=a.id, item_id=it.id, grader_id=u.id, kind=it.kind, rationale=rationale[:4000], flags=list(flags))
        if it.kind == "absolute":
            try:
                j.scores = {d: int(form[f"score_{d}"]) for d in dim_ids()}
            except (KeyError, ValueError):
                raise HTTPException(400, "Score every dimension (1-7).") from None
            if not all(1 <= v <= 7 for v in j.scores.values()):
                raise HTTPException(400, "Scores must be 1-7.")
            j.acceptable = form.get("acceptable") == "yes"
            if it.is_attention:
                j.attention_passed = all(j.scores.get(k) == v for k, v in (it.attention or {}).items())
            if it.is_gold:
                lo, hi = it.gold["overall"]
                o = j.scores["overall"]
                j.gold_deviation = 0.0 if lo <= o <= hi else min(abs(o - lo), abs(o - hi))
        else:
            left, right = (it.run_a, it.run_b) if it.left_is_a else (it.run_b, it.run_a)
            winners = {}
            for d in dim_ids():
                v = form.get(f"win_{d}")
                if v not in ("left", "right", "tie"):
                    raise HTTPException(400, "Choose left, right or tie for every dimension.")
                winners[d] = {"left": left, "right": right, "tie": "tie"}[v]
            j.winners = winners
        a.status, a.submitted_at = "done", utcnow()
        a.seconds_on_task = (a.submitted_at - a.started_at).total_seconds() if a.started_at else None
        s.add(j)
        if "manipulation" in flags or "broken" in flags:
            s.add(Flag(item_id=it.id, grader_id=u.id, reason=", ".join(flags)))
        s.commit()
    return RedirectResponse("/next", 303)


@app.post("/flag/{aid}")
def flag(request: Request, aid: int, reason: str = Form(...)):
    u = need(request)
    with session() as s:
        a = s.get(Assignment, aid)
        if not a or a.grader_id != u.id:
            raise HTTPException(404, "not your assignment")
        s.add(Flag(item_id=a.item_id, grader_id=u.id, reason=reason[:1000]))
        s.commit()
    return RedirectResponse(f"/grade/{aid}", 303)


# ------------------------------------------------------------------ blind assets
@app.get("/b/{a}/file/{path:path}")
def blind_file(request: Request, a: str, path: str):
    need(request)
    b = bundle_for(a)
    if not re.match(r"^(screenshots/(desktop|mobile)|ads/previews)/[\w.-]+\.png$", path):
        raise HTTPException(404, "not served")
    return FileResponse(b / path)


# ------------------------------------------------------------------ admin
def _human_alpha(round_name: str | None = None) -> dict:
    with session() as s:
        q = select(Judgment, Item).join(Item, Judgment.item_id == Item.id).where(Item.kind == "absolute", Item.is_gold.is_(False), Item.is_attention.is_(False))
        if round_name:
            q = q.where(Item.round == round_name)
        rows = s.execute(q).all()
    out = {}
    for d in dim_ids():
        units: dict[str, list[float]] = {}
        for j, it in rows:
            units.setdefault(it.run_a, []).append(j.scores[d])
        out[d] = krippendorff_alpha(units)
    return out


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    u = need(request, admin=True)
    with session() as s:
        graders = s.scalars(select(Grader).order_by(Grader.id)).all()
        rounds = [r for (r,) in s.execute(select(Item.round).distinct()).all()]
        stats = []
        for g in graders:
            done = s.scalars(select(Assignment).where(Assignment.grader_id == g.id, Assignment.status == "done")).all()
            pend = s.scalar(select(func.count()).select_from(Assignment).where(Assignment.grader_id == g.id, Assignment.status == "pending"))
            secs = [a.seconds_on_task for a in done if a.seconds_on_task]
            js = s.scalars(select(Judgment).where(Judgment.grader_id == g.id)).all()
            stats.append({"g": g, "done": len(done), "pending": pend, "median_s": statistics.median(secs) if secs else None,
                          "too_fast": sum(1 for x in secs if x < 45), "attention_fail": sum(1 for j in js if j.attention_passed is False),
                          "gold_dev": max((j.gold_deviation for j in js if j.gold_deviation is not None), default=None)})
        items_total = s.scalar(select(func.count()).select_from(Item))
        asg_total = s.scalar(select(func.count()).select_from(Assignment))
        asg_done = s.scalar(select(func.count()).select_from(Assignment).where(Assignment.status == "done"))
        flags = s.execute(select(Flag, Item, Grader).join(Item, Flag.item_id == Item.id).join(Grader, Flag.grader_id == Grader.id).order_by(Flag.id.desc())).all()
        contacts = s.scalars(select(Contact).order_by(Contact.id.desc()).limit(50)).all()
    results = {}
    for r in rounds:
        p = settings.runs_dir / r / "results.json"
        if p.exists():
            results[r] = json.loads(p.read_text())
    return templates.TemplateResponse(request, "admin.html", {
        "u": u, "stats": stats, "rounds": rounds, "items_total": items_total, "asg_total": asg_total, "asg_done": asg_done,
        "alpha": _human_alpha(), "results": results, "flags": flags, "contacts": contacts, "dims": dim_ids(), "alias": alias})


@app.post("/admin/graders")
def add_grader(request: Request, username: str = Form(...), password: str = Form(...), role: str = Form("grader")):
    need(request, admin=True)
    with session() as s:
        if s.scalar(select(Grader).where(Grader.username == username)):
            raise HTTPException(400, "username exists")
        s.add(Grader(username=username[:80], password_hash=hash_pw(password), role="admin" if role == "admin" else "grader"))
        s.commit()
    return RedirectResponse("/admin", 303)


@app.get("/admin/export.{fmt}")
def export(request: Request, fmt: str):
    need(request, admin=True)
    with session() as s:
        rows = s.execute(select(Judgment, Item, Grader, Assignment).join(Item, Judgment.item_id == Item.id).join(Grader, Judgment.grader_id == Grader.id)
                         .join(Assignment, Judgment.assignment_id == Assignment.id)).all()
    data = [{"round": it.round, "item": it.id, "kind": it.kind, "task": it.task_id, "run_a": it.run_a, "run_b": it.run_b, "grader": g.username,
             "synthetic_grader": g.synthetic, "gold": it.is_gold, "attention": it.is_attention, "attention_passed": j.attention_passed,
             "gold_deviation": j.gold_deviation, "seconds": a.seconds_on_task, "scores": j.scores, "winners": j.winners, "acceptable": j.acceptable,
             "flags": j.flags, "rationale": j.rationale, "at": j.created_at.isoformat()} for j, it, g, a in rows]
    if fmt == "json":
        return JSONResponse(data)
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = ["round", "item", "kind", "task", "run_a", "run_b", "grader", "synthetic_grader", "gold", "attention", "attention_passed", "gold_deviation", "seconds", "acceptable"]
    w.writerow(cols + [f"score_{d}" for d in dim_ids()] + [f"win_{d}" for d in dim_ids()] + ["rationale"])
    for r in data:
        w.writerow([r[c] for c in cols] + [(r["scores"] or {}).get(d) for d in dim_ids()] + [(r["winners"] or {}).get(d) for d in dim_ids()] + [r["rationale"]])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


# ------------------------------------------------------------------ public contact endpoint (company site)
@app.post("/api/contact")
async def contact(request: Request):
    ctype = request.headers.get("content-type", "")
    data = await request.json() if "json" in ctype else dict(await request.form())
    clean = {k: str(v)[:2000] for k, v in data.items() if k in ("name", "email", "org", "org_type", "interest", "timeline", "message")}
    if "@" not in clean.get("email", ""):
        return JSONResponse({"ok": False, "error": "email required"}, 400)
    with session() as s:
        s.add(Contact(data=clean))
        s.commit()
    return {"ok": True}


# ------------------------------------------------------------------ dashboard (admin, unblinded)
def _rounds() -> list[str]:
    return sorted(p.parent.name for p in settings.runs_dir.glob("*/results.json")) if settings.runs_dir.exists() else []


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, round: str | None = None):
    u = need(request, admin=True)
    rounds = _rounds()
    if not rounds:
        return templates.TemplateResponse(request, "dashboard.html", {"u": u, "rounds": [], "res": None})
    rname = round or rounds[-1]
    res = json.loads((settings.runs_dir / rname / "results.json").read_text())
    ci_rows = [{"label": x["model"], "mean": x["overall"]["combined"]["mean"], "lo": x["overall"]["combined"]["lo"], "hi": x["overall"]["combined"]["hi"],
                "note": f"{x['n_runs']} runs"} for x in res["models"]]
    cost_pts = [{"label": x["model"], "x": x["cost_usd_mean"], "y": x["overall"]["combined"]["mean"]} for x in res["models"] if x["cost_usd_mean"]]
    return templates.TemplateResponse(request, "dashboard.html", {"u": u, "rounds": rounds, "rname": rname, "res": res, "dims": dimensions(),
                                                                 "ci_rows": ci_rows, "cost_pts": cost_pts})


@app.get("/dashboard/run/{run_id}", response_class=HTMLResponse)
def run_view(request: Request, run_id: str):
    u = need(request, admin=True)
    b = run_bundle(run_id)
    rd = b.parent.parent
    judgments = [json.loads(line) for line in (rd / "judgments" / "llm_absolute.jsonl").read_text().splitlines()] if (rd / "judgments" / "llm_absolute.jsonl").exists() else []
    res = json.loads((rd / "results.json").read_text()) if (rd / "results.json").exists() else {"runs": []}
    row = next((r for r in res["runs"] if r["run_id"] == run_id), None)
    ev = evidence(run_id)
    return templates.TemplateResponse(request, "run.html", {"u": u, "run_id": run_id, "ev": ev, "row": row, "dims": dimensions(), "rname": rd.name,
                                                           "judgments": [j for j in judgments if j["run_id"] == run_id],
                                                           "site_url": f"{request.url.scheme}://{ev['alias'].lower()}.localhost{':' + str(request.url.port) if request.url.port else ''}/"})


@app.get("/dashboard/run/{run_id}/trajectory", response_class=HTMLResponse)
def trajectory(request: Request, run_id: str, page: int = 1):
    u = need(request, admin=True)
    b = run_bundle(run_id)
    events = [json.loads(line) for line in (b / "trajectory.jsonl").read_text().splitlines()]
    per = 60
    pages = max(1, (len(events) + per - 1) // per)
    return templates.TemplateResponse(request, "trajectory.html", {"u": u, "run_id": run_id, "events": events[(page - 1) * per: page * per],
                                                                  "page": page, "pages": pages, "total": len(events)})


@app.get("/dashboard/run/{run_id}/file/{path:path}")
def run_file(request: Request, run_id: str, path: str):
    need(request, admin=True)
    b = run_bundle(run_id)
    p = (b / path).resolve()
    if b.resolve() not in p.parents or not p.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(p)


@app.get("/reports/{round_name}", response_class=HTMLResponse)
def report(request: Request, round_name: str):
    need(request, admin=True)
    p = settings.runs_dir / round_name / "report" / "report.html"
    if not p.exists():
        raise HTTPException(404, "report not generated yet: run `shingle report`")
    return HTMLResponse(p.read_text())


@app.get("/reports/{round_name}/{asset:path}")
def report_asset(request: Request, round_name: str, asset: str):
    need(request, admin=True)
    base = (settings.runs_dir / round_name / "report").resolve()
    p = (base / asset).resolve()
    if base not in p.parents or not p.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(p)


@app.get("/static/app.css")
def css():
    return FileResponse(HERE / "static" / "app.css", media_type="text/css")


@app.get("/static/app.js")
def js():
    return FileResponse(HERE / "static" / "app.js", media_type="application/javascript")
