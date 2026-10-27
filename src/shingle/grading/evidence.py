"""Blinding + evidence packets: what graders (human or LLM) see for one run.

Model identity is never shown. Model/provider names and AI self-references are scrubbed
from every text artifact, and runs are referred to by keyed aliases.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from pathlib import Path

from ..checks.content import _visible_text
from ..config import get_settings

FINGERPRINTS = [
    r"\bas an ai(?: language)? model\b[^.]*\.?", r"\bi am an ai\b[^.]*\.?", r"\bclaude(?:[- ]\w+)?\b", r"\banthropic\b", r"\bchat ?gpt\b", r"\bgpt-?\d[\w.-]*\b",
    r"\bopenai\b", r"\bgemini(?:[- ][\w.]+)?\b", r"\bllama[- ]?\d*[\w.-]*\b", r"\bmistral\b", r"\bqwen\w*\b", r"\bdeepseek\w*\b",
    r"\bmock-(?:diligent|hasty)\b", r"\bmock[- ]?model\b",
]
_FP = re.compile("|".join(FINGERPRINTS), re.I)


def scrub(text: str) -> str:
    return _FP.sub("[redacted]", text)


def alias(run_id: str, salt: str = "") -> str:
    key = (get_settings().secret_key + salt).encode()
    return "B-" + hmac.new(key, run_id.encode(), hashlib.sha256).hexdigest()[:6].upper()


def wrap(label: str, text: str) -> str:
    """Model-produced content is data, not instructions."""
    text = text.replace("</untrusted_artifact>", "</untrusted_artifact_>")
    return f'<untrusted_artifact source="{label}">\n{scrub(text)}\n</untrusted_artifact>'


def week_timeline(bundle: Path) -> list[dict]:
    out = []
    for f in sorted((bundle / "market").glob("week_*.json"), key=lambda p: int(p.stem.split("_")[1])):
        w = json.loads(f.read_text())
        out.append({"week": w["week"], "totals": w["totals"], "site_issues": w["site"].get("issues", []),
                    "feedback": [q["quote"] for q in w.get("feedback", [])][:4]})
    return out


def change_log(bundle: Path) -> list[str]:
    """What the agent changed after launch (ads, deploys, prices), by week, from the trajectory."""
    out, week = [], 0
    for line in (bundle / "trajectory.jsonl").read_text().splitlines():
        e = json.loads(line)
        if e["type"] == "week_report":
            week = e["week"]
        if e["type"] == "tool_call" and week >= 1 and not e["is_error"] and e["name"] in (
                "ads_update", "ads_create_ad", "ads_create_ad_set", "deploy_site", "payments_create_price", "payments_update_price",
                "suppliers_place_order", "write_file"):
            arg = e["args"].get("path") or e["args"].get("object_id") or ""
            out.append(f"after week {week}: {e['name']} {arg}".strip())
    return out


def packet(bundle: Path, task, include_images: bool = True) -> dict:
    m = json.loads((bundle / "manifest.json").read_text())
    checks = json.loads((bundle / "checks.json").read_text()) if (bundle / "checks.json").exists() else {}
    pages = {}
    for p in m.get("pages", [])[:8]:
        rel = (p.strip("/") or "index")
        for cand in (f"{rel}.html", f"{rel}/index.html", "index.html" if p == "/" else ""):
            f = bundle / "site" / cand
            if cand and f.exists():
                pages[p] = _visible_text(f.read_text(errors="ignore"))[:3500]
                break
    docs = {d: (bundle / d).read_text()[:6000] for d in ("docs/brand.md", "docs/business_plan.md", "docs/launch_plan.md") if (bundle / d).exists()}
    creatives = json.loads((bundle / "ads" / "creatives.json").read_text()) if (bundle / "ads" / "creatives.json").exists() else []
    ads = [{"ad": c["ad_id"], "status": c["status"], "headline": c["creative"]["headline"], "primary_text": c["creative"]["primary_text"],
            "cta": c["creative"]["cta"], "landing": c["creative"]["landing_path"], "targeting": c["targeting"]} for c in creatives]
    sup = json.loads((bundle / "commerce" / "suppliers.json").read_text()) if (bundle / "commerce" / "suppliers.json").exists() else {}
    pay = json.loads((bundle / "platform.json").read_text())["payments"] if (bundle / "platform.json").exists() else {"prices": {}, "products": {}}
    prices = [{"product": pay["products"].get(p["product"], {}).get("name"), "amount": p["unit_amount"] / 100, "currency": p["currency"],
               "recurring": p["recurring"], "active": p["active"]} for p in pay["prices"].values()]
    images = []
    if include_images:
        for mode in ("desktop", "mobile"):
            images += [bundle / s["file"] for s in m["screenshots"].get(mode, [])[:3] if "file" in s]
        images += [bundle / a["file"] for a in m.get("ad_previews", [])[:2]]
    res = checks.get("results", {})
    check_ctx = {"summary": checks.get("summary"), "site_works_gate": checks.get("site_works_gate"),
                 "product_qa": [{k: c.get(k) for k in ("id", "result", "evidence")} for c in res.get("product_qa", {}).get("criteria", [])],
                 "integrity_flags": [{k: f[k] for k in ("category", "severity", "match", "occurrences")} for f in res.get("integrity", {}).get("flags", [])][:25],
                 "lighthouse": res.get("lighthouse", {}).get("scores"), "mobile_problems": res.get("mobile", {}).get("problems"),
                 "ad_compliance": [{k: a[k] for k in ("ad_id", "problems", "warnings")} for a in res.get("ad_compliance", {}).get("ads", [])],
                 "supplier": {k: res.get("supplier", {}).get(k) for k in ("status", "problems", "notes", "orders")}}
    return {"run_id": m["run_id"], "alias": alias(m["run_id"]), "task_id": task.id, "pages": pages, "docs": docs, "ads": ads, "prices": prices,
            "supplier_orders": sup.get("orders", []), "weeks": week_timeline(bundle), "changes": change_log(bundle), "checks": check_ctx,
            "images": [str(i) for i in images if i.exists()], "deliverables": m.get("deliverables")}


def packet_text(p: dict, task, label: str = "") -> str:
    tag = f" {label}" if label else ""
    parts = [f"# BUSINESS{tag} ({p['alias']})"]
    for path, text in p["pages"].items():
        parts.append(wrap(f"site page {path}", text))
    for d, text in p["docs"].items():
        parts.append(wrap(d, text))
    parts.append(wrap("ads (creatives + targeting)", json.dumps(p["ads"], indent=1)))
    parts.append(wrap("prices in checkout", json.dumps(p["prices"])))
    if p["supplier_orders"]:
        parts.append("Supplier orders (system record): " + json.dumps([{k: o[k] for k in ("supplier", "sku", "quantity", "landed_unit_cost", "arrives_week")} for o in p["supplier_orders"]]))
    parts.append("Weekly SIMULATED market results (system record, directional only): " + json.dumps(p["weeks"]))
    parts.append("Changes made after launch (system record): " + json.dumps(p["changes"][:60]))
    parts.append("Automated checks (system record, context only): " + json.dumps(p["checks"]))
    return "\n\n".join(parts)
