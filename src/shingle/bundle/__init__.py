"""Run bundles: everything graders need, frozen at episode end.

bundle/
  manifest.json        run metadata + deliverable inventory
  site/ platform.json  frozen site + payment catalog (re-servable exactly as deployed)
  source/              the agent's workspace (code, docs, notes, assets)
  docs/                brand.md, business_plan.md, launch_plan.md (if produced)
  screenshots/         desktop/ and mobile/ PNGs of key pages
  ads/                 campaigns.json, creatives.json, previews/<ad_id>.png
  commerce/            payments.json, suppliers.json, ledger.json, forms.json
  market/              week_<n>.json (simulated; labeled)
  trajectory.jsonl     full log of model turns and tool calls
  usage.json           tokens, cost, wall clock
  checks.json          automated check results (added by shingle.checks)
"""

from __future__ import annotations

import base64
import html
import json
import shutil
import zipfile
from pathlib import Path

from ..browser import browser, new_page
from ..sandbox.hosting import PreviewServer, frozen_platform

DOCS = ("docs/brand.md", "docs/business_plan.md", "docs/launch_plan.md")


def _copy(src: Path, dst: Path) -> None:
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=shutil.ignore_patterns("node_modules", ".git"))
    elif src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def key_pages(task, site_dir: Path) -> list[str]:
    pages = ["/"] + [f"/{p.strip('/')}" for p in task.required_pages]
    for p in sorted(site_dir.rglob("*.html")):
        rel = "/" + str(p.relative_to(site_dir)).removesuffix("index.html").removesuffix(".html")
        if rel not in pages and len(pages) < 10 and "404" not in rel:
            pages.append(rel.rstrip("/") or "/")
    return list(dict.fromkeys(pages))


AD_CARD = """<!doctype html><html><head><meta charset=utf-8><style>
body{{margin:0;background:#f0f2f5;font:14px/1.4 system-ui,sans-serif}}.c{{width:400px;margin:16px;background:#fff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px #0003}}
.h{{display:flex;gap:8px;align-items:center;padding:10px 12px}}.av{{width:32px;height:32px;border-radius:50%;background:#ccc}}.n{{font-weight:700}}.s{{color:#65676b;font-size:12px}}
.t{{padding:0 12px 10px;white-space:pre-wrap}}img{{width:100%;display:block}}.f{{display:flex;justify-content:space-between;align-items:center;padding:10px 12px;background:#f7f8fa}}
.hl{{font-weight:700}}.d{{color:#65676b;font-size:12px}}.b{{background:#e4e6eb;border-radius:6px;padding:8px 12px;font-weight:600;white-space:nowrap}}</style></head><body>
<div class=c><div class=h><div class=av></div><div><div class=n>{brand}</div><div class=s>Sponsored · simulated</div></div></div>
<div class=t>{text}</div><img src="data:image/png;base64,{img}"><div class=f><div><div class=hl>{headline}</div><div class=d>{desc}</div></div><div class=b>{cta}</div></div></div></body></html>"""


def build_bundle(run_dir: Path, world) -> Path:
    """Freeze the world into run_dir/bundle. Call after the episode, before world.close()."""
    b = run_dir / "bundle"
    if b.exists():
        shutil.rmtree(b)
    b.mkdir(parents=True)
    task = world.task
    frozen = world.hosting.freeze(b / "_frozen")
    if frozen.get("frozen"):
        shutil.move(str(b / "_frozen" / "site"), b / "site")
        shutil.move(str(b / "_frozen" / "platform.json"), b / "platform.json")
    shutil.rmtree(b / "_frozen", ignore_errors=True)
    _copy(world.ws.root, b / "source")
    for d in DOCS:
        _copy(world.ws.root / d, b / d)
    st = world.state_dir
    (b / "ads").mkdir()
    _copy(st / "ads.json", b / "ads" / "campaigns.json")
    _copy(st / "images.jsonl", b / "ads" / "image_prompts.jsonl")
    (b / "commerce").mkdir()
    for name in ("payments.json", "suppliers.json", "ledger.json"):
        _copy(st / name, b / "commerce" / name)
    (b / "commerce" / "forms.json").write_text(json.dumps(world.hosting.platform.state.get("forms", []), indent=2))
    _copy(st / "market", b / "market")
    _copy(run_dir / "trajectory.jsonl", b / "trajectory.jsonl")
    run = json.loads((run_dir / "run.json").read_text())
    (b / "usage.json").write_text(json.dumps({k: run[k] for k in ("usage", "cost_usd", "wall_clock_s", "steps", "summaries")}, indent=2))

    ads = world.ads.state
    creatives = []
    for a in ads.get("ads", {}).values():
        s = ads["ad_sets"][a["ad_set_id"]]
        creatives.append({"ad_id": a["id"], "name": a["name"], "status": a["status"], "creative": a["creative"], "image": a["image"],
                          "targeting": s["targeting"], "ad_set": s["id"], "campaign": s["campaign_id"], "created_week": a["created_week"]})
    (b / "ads" / "creatives.json").write_text(json.dumps(creatives, indent=2))

    shots = {"desktop": [], "mobile": []}
    previews = []
    pages = key_pages(task, b / "site") if (b / "site").exists() else []
    with browser() as br:
        if pages:
            plat = frozen_platform(b, run_dir / "state" / "bundle_scratch.json")
            srv = PreviewServer(plat)
            try:
                for mode in ("desktop", "mobile"):
                    (b / "screenshots" / mode).mkdir(parents=True, exist_ok=True)
                    for p in pages:
                        page, _ = new_page(br, mobile=mode == "mobile", source="bundle")
                        try:
                            r = page.goto(srv.url + p, wait_until="load")
                            page.wait_for_timeout(150)
                            name = (p.strip("/") or "home").replace("/", "_")
                            out = b / "screenshots" / mode / f"{name}.png"
                            h = min(page.evaluate("document.documentElement.scrollHeight"), 5000)
                            page.set_viewport_size({"width": page.viewport_size["width"], "height": max(page.viewport_size["height"], h)})
                            page.screenshot(path=str(out), full_page=False)
                            shots[mode].append({"page": p, "file": f"screenshots/{mode}/{name}.png", "status": r.status if r else 0})
                        except Exception as e:
                            shots[mode].append({"page": p, "error": str(e)[:200]})
                        finally:
                            page.context.close()
            finally:
                srv.close()
        (b / "ads" / "previews").mkdir(parents=True, exist_ok=True)
        brand = _brand_name(b)
        for c in creatives:
            img = world.ws.root / c["creative"]["image_path"].lstrip("/")
            if not img.exists():
                continue
            cr = c["creative"]
            doc = AD_CARD.format(brand=html.escape(brand), text=html.escape(cr["primary_text"]), img=base64.b64encode(img.read_bytes()).decode(),
                                 headline=html.escape(cr["headline"]), desc=html.escape(cr.get("description", "")), cta=cr["cta"].replace("_", " ").title())
            page, _ = new_page(br, source="bundle")
            try:
                page.set_content(doc)
                out = b / "ads" / "previews" / f"{c['ad_id']}.png"
                page.locator(".c").screenshot(path=str(out))
                previews.append({"ad_id": c["ad_id"], "file": f"ads/previews/{c['ad_id']}.png"})
            finally:
                page.context.close()

    present = {d: (b / d).exists() and len((b / d).read_text().strip()) > 200 for d in DOCS}
    manifest = {**run, "bundle_version": 1, "frozen_site": bool(frozen.get("frozen")), "site_version": frozen.get("version"),
                "pages": pages, "screenshots": shots, "ad_previews": previews, "deliverables": {
                    "website": bool(frozen.get("frozen")), **{Path(d).stem: ok for d, ok in present.items()},
                    "ad_campaign": bool(creatives), "checkout_prices": bool(world.payments.catalog()),
                    "supplier_order": bool(world.suppliers.state.get("orders")),
                    "product_images": any((b / "site").rglob("*.png")) if (b / "site").exists() else False},
                "market_weeks": sorted(p.name for p in (b / "market").glob("week_*.json")) if (b / "market").exists() else [],
                "simulated_market_notice": "Market results are produced by a simulated customer panel and are a secondary, directional signal."}
    (b / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return b


def _brand_name(b: Path) -> str:
    brand = b / "docs" / "brand.md"
    if brand.exists():
        first = brand.read_text().strip().splitlines()[0]
        return first.lstrip("# ").split(":")[0].strip()[:40] or "Sponsored"
    return "Sponsored"


def export_bundle(bundle: Path, out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(bundle.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(bundle.parent))
    return out
