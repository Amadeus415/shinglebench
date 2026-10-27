"""Grading database (SQLite locally, Postgres via DATABASE_URL)."""

from __future__ import annotations

import hashlib
import json
import os
import random
import secrets
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from ..config import get_settings
from ..grading.evidence import alias


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Grader(Base):
    __tablename__ = "graders"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    role: Mapped[str] = mapped_column(String(20), default="grader")  # grader | admin
    synthetic: Mapped[bool] = mapped_column(Boolean, default=False)  # scripted demo account, never a real human
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Item(Base):
    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    round: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # absolute | pairwise
    task_id: Mapped[str] = mapped_column(String(80))
    run_a: Mapped[str] = mapped_column(String(200))
    run_b: Mapped[str | None] = mapped_column(String(200), nullable=True)
    left_is_a: Mapped[bool] = mapped_column(Boolean, default=True)
    is_gold: Mapped[bool] = mapped_column(Boolean, default=False)
    gold: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"overall": [lo, hi]}
    is_attention: Mapped[bool] = mapped_column(Boolean, default=False)
    attention: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"brand": 2}
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    grader_id: Mapped[int] = mapped_column(ForeignKey("graders.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | done | skipped
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    seconds_on_task: Mapped[float | None] = mapped_column(Float, nullable=True)


class Judgment(Base):
    __tablename__ = "judgments"
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id"), unique=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"), index=True)
    grader_id: Mapped[int] = mapped_column(ForeignKey("graders.id"))
    kind: Mapped[str] = mapped_column(String(20))
    scores: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # absolute: dim -> 1..7
    winners: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # pairwise: dim -> run_id | "tie"
    rationale: Mapped[str] = mapped_column(Text, default="")
    acceptable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    attention_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gold_deviation: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Flag(Base):
    __tablename__ = "flags"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("items.id"))
    grader_id: Mapped[int] = mapped_column(ForeignKey("graders.id"))
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


_engine = None
_Session = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = get_settings().database_url
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(url, future=True, pool_pre_ping=True)
        Base.metadata.create_all(_engine)
        _Session = sessionmaker(_engine, expire_on_commit=False)
        with session() as s:
            ensure_default_users(s)
    return _engine


def session() -> Session:
    if _Session is None:
        engine()
    return _Session()


def hash_pw(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000).hex()}"


def check_pw(pw: str, stored: str) -> bool:
    salt = stored.split("$", 1)[0]
    return secrets.compare_digest(hash_pw(pw, salt), stored)


def ensure_default_users(s: Session) -> None:
    """Local/dev accounts. Override passwords with ADMIN_PASSWORD / GRADER_PASSWORD."""
    defaults = [("admin", os.environ.get("ADMIN_PASSWORD", "admin"), "admin", False),
                ("grader1", os.environ.get("GRADER_PASSWORD", "grader"), "grader", False),
                ("grader2", os.environ.get("GRADER_PASSWORD", "grader"), "grader", False),
                ("demo-grader-1", secrets.token_hex(12), "grader", True),
                ("demo-grader-2", secrets.token_hex(12), "grader", True)]
    for u, pw, role, synth in defaults:
        if not s.scalar(select(Grader).where(Grader.username == u)):
            s.add(Grader(username=u, password_hash=hash_pw(pw), role=role, synthetic=synth))
    s.commit()


def populate_round(round_dir: Path, per_item: int = 2, seed: int = 0) -> int:
    """Create blind grading items for a round (idempotent) and assign them to graders."""
    from ..grading.aggregate import round_runs

    rname = round_dir.name
    runs = round_runs(round_dir)
    rng = random.Random(f"{rname}|{seed}")
    with session() as s:
        if s.scalar(select(Item).where(Item.round == rname)):
            return 0
        graders = [g for g in s.scalars(select(Grader).where(Grader.role == "grader")).all()]
        items: list[Item] = []
        for r in runs:
            items.append(Item(round=rname, kind="absolute", task_id=r["manifest"]["task_id"], run_a=r["manifest"]["run_id"]))
        by_task: dict[tuple[str, int], list[dict]] = {}
        for r in runs:
            by_task.setdefault((r["manifest"]["task_id"], r["manifest"]["seed"]), []).append(r["manifest"])
        for (tid, _), ms in sorted(by_task.items()):
            for i in range(len(ms)):
                for j in range(i + 1, len(ms)):
                    if ms[i]["model"] != ms[j]["model"]:
                        items.append(Item(round=rname, kind="pairwise", task_id=tid, run_a=ms[i]["run_id"], run_b=ms[j]["run_id"], left_is_a=rng.random() < 0.5))
        # QC: gold items (LLM-consensus extremes with an expected band) and one attention check
        llm = {}
        if (round_dir / "judgments" / "llm_absolute.jsonl").exists():
            for line in (round_dir / "judgments" / "llm_absolute.jsonl").read_text().splitlines():
                j = json.loads(line)
                llm.setdefault(j["run_id"], []).append(j["scores"]["overall"])
        ranked = sorted(llm.items(), key=lambda kv: sum(kv[1]) / len(kv[1]))
        for rid, sc in ([ranked[0], ranked[-1]] if len(ranked) >= 2 else []):
            m = sum(sc) / len(sc)
            items.append(Item(round=rname, kind="absolute", task_id=rid.split("__")[0], run_a=rid, is_gold=True, gold={"overall": [max(1, m - 1.5), min(7, m + 1.5)]}))
        if runs:
            r0 = rng.choice(runs)["manifest"]
            items.append(Item(round=rname, kind="absolute", task_id=r0["task_id"], run_a=r0["run_id"], is_attention=True, attention={"brand": 2, "iteration": 6}))
        s.add_all(items)
        s.flush()
        for it in items:
            pool = graders if (it.is_gold or it.is_attention) else rng.sample(graders, k=min(per_item, len(graders)))
            for g in pool:
                s.add(Assignment(item_id=it.id, grader_id=g.id))
        s.commit()
        return len(items)


def export_human_judgments(round_name: str, include_synthetic: bool = True) -> tuple[list[dict], list[dict]]:
    with session() as s:
        rows = s.execute(select(Judgment, Item, Grader).join(Item, Judgment.item_id == Item.id).join(Grader, Judgment.grader_id == Grader.id)
                         .where(Item.round == round_name)).all()
    abs_out, pair_out = [], []
    for j, it, g in rows:
        if g.synthetic and not include_synthetic:
            continue
        base = {"grader": g.username, "synthetic": g.synthetic, "is_gold": it.is_gold, "is_attention": it.is_attention,
                "excluded": j.attention_passed is False}
        if it.kind == "absolute":
            abs_out.append(base | {"run_id": it.run_a, "scores": j.scores, "acceptable": j.acceptable})
        else:
            pair_out.append(base | {"a": it.run_a, "b": it.run_b, "winners": j.winners})
    return abs_out, pair_out


def item_aliases(it: Item) -> tuple[str, str | None]:
    return alias(it.run_a), alias(it.run_b) if it.run_b else None



def simulate_demo_graders(round_dir: Path, seed: int = 7) -> int:
    """Fill the synthetic demo accounts' queues so human-side views (agreement, QC, combined scores) have data.

    These are NOT human judgments: scores are the LLM-judge mean plus per-grader bias and noise, and the
    accounts are flagged `synthetic` everywhere they appear. demo-grader-2 deliberately fails one attention check.
    """
    from datetime import timedelta

    from ..grading.rubric import dim_ids

    rname = round_dir.name
    llm: dict[str, dict[str, list[float]]] = {}
    p = round_dir / "judgments" / "llm_absolute.jsonl"
    for line in p.read_text().splitlines() if p.exists() else []:
        j = json.loads(line)
        for d, v in j["scores"].items():
            llm.setdefault(j["run_id"], {}).setdefault(d, []).append(v)
    rng = random.Random(f"{rname}|{seed}")
    n = 0
    with session() as s:
        demo = s.scalars(select(Grader).where(Grader.synthetic.is_(True))).all()
        for gi, g in enumerate(demo):
            bias = (0.3, -0.4)[gi % 2]
            failed_attention = False
            rows = s.execute(select(Assignment, Item).join(Item, Assignment.item_id == Item.id)
                             .where(Assignment.grader_id == g.id, Assignment.status == "pending", Item.round == rname)).all()
            for a, it in rows:
                def est(run: str, d: str) -> float:
                    v = llm.get(run, {}).get(d)
                    return sum(v) / len(v) if v else 4.0
                j = Judgment(assignment_id=a.id, item_id=it.id, grader_id=g.id, kind=it.kind, flags=[],
                             rationale="Scripted demo grader (synthetic, not a human judgment).")
                if it.kind == "absolute":
                    j.scores = {d: max(1, min(7, round(est(it.run_a, d) + bias + rng.gauss(0, 0.9)))) for d in dim_ids()}
                    j.acceptable = j.scores["overall"] >= 5
                    if it.is_attention:
                        if gi % 2 == 1 and not failed_attention:
                            failed_attention = True  # demonstrates QC catching an inattentive grader
                        else:
                            j.scores.update(it.attention or {})
                        j.attention_passed = all(j.scores.get(k) == v for k, v in (it.attention or {}).items())
                    if it.is_gold:
                        lo, hi = it.gold["overall"]
                        o = j.scores["overall"]
                        j.gold_deviation = 0.0 if lo <= o <= hi else min(abs(o - lo), abs(o - hi))
                else:
                    w = {}
                    for d in dim_ids():
                        diff = est(it.run_a, d) - est(it.run_b, d) + rng.gauss(0, 0.8)
                        w[d] = it.run_a if diff > 0.6 else it.run_b if diff < -0.6 else "tie"
                    j.winners = w
                a.status = "done"
                a.started_at = utcnow()
                a.seconds_on_task = rng.uniform(150, 720)
                a.submitted_at = a.started_at + timedelta(seconds=a.seconds_on_task)
                s.add(j)
                n += 1
        s.commit()
    return n


def reset_round(round_name: str) -> None:
    """Delete a round's items, assignments and judgments (used by `shingle demo --fresh`)."""
    with session() as s:
        ids = [i for (i,) in s.execute(select(Item.id).where(Item.round == round_name)).all()]
        for model in (Judgment, Assignment, Flag):
            for row in s.scalars(select(model).where(model.item_id.in_(ids))).all():
                s.delete(row)
        for row in s.scalars(select(Item).where(Item.id.in_(ids))).all():
            s.delete(row)
        s.commit()
