"""The tool interface every model under test gets (identical across models)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable

from ..browser import browser, new_page, render_snapshot, snapshot
from ..market.simulator import render_report
from ..sandbox.ads import AdsError
from ..sandbox.payments import PaymentsError
from ..sandbox.suppliers import SupplierError
from ..sandbox.workspace import WorkspaceError

NOTES = "NOTES.md"
TOOLSET_VERSION = "t1"


@dataclass
class Tool:
    name: str
    description: str
    params: dict  # JSON schema "properties"
    required: list[str]
    fn: Callable[[Any, dict], str]

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": {"type": "object", "properties": self.params, "required": self.required, "additionalProperties": False}}


def _j(x) -> str:
    return json.dumps(x, indent=1, default=str)


S = {"type": "string"}
I = {"type": "integer"}
N = {"type": "number"}
O = {"type": "object"}


# ---------------------------------------------------------------- handlers
def t_shell(w, a):
    return w.shell.run(a["command"], timeout=min(int(a.get("timeout_s", 60)), 300)).render()


def t_write(w, a):
    p = w.ws.write(a["path"], a["content"])
    return f"wrote {p.relative_to(w.ws.root)} ({len(a['content'])} chars)"


def t_read(w, a):
    return w.ws.read(a["path"])


def t_list(w, a):
    files = w.ws.list(a.get("path", "."))
    return "\n".join(files) or "(empty)"


def t_deploy(w, a):
    r = w.hosting.deploy(a.get("directory", "site"))
    return _j(r | {"note": "Deployed. Simulated visitors and ad clicks reach this version. Re-deploy after edits."})


def t_view(w, a):
    if not w.hosting.server:
        return "ERROR: nothing deployed yet; call deploy_site first"
    path = a.get("path", "/")
    with browser() as b:
        page, errs = new_page(b, mobile=a.get("viewport") == "mobile", source="agent")
        try:
            resp = page.goto(w.hosting.server.url + path, wait_until="load")
            out = f"HTTP {resp.status if resp else '?'}\n" + render_snapshot(snapshot(page), errs)
        finally:
            page.context.close()
    return out


def t_image(w, a):
    size = a.get("size", "square")
    if size not in ("square", "portrait", "landscape", "hero"):
        return "ERROR: size must be square (1080x1080), portrait (1080x1350), landscape (1200x628) or hero (1600x900)"
    name = a["filename"].removesuffix(".png")
    data = w.images.generate(a["prompt"], size=size, seed=w.seed)
    rel = f"assets/{name}.png"
    w.ws.write(rel, data)
    w.ws.write(f"site/assets/{name}.png", data)
    log = w.state_dir / "images.jsonl"
    with log.open("a") as f:
        f.write(json.dumps({"week": w.week(), "file": rel, "prompt": a["prompt"], "size": size, "provider": w.images.name}) + "\n")
    return f"saved {rel} and site/assets/{name}.png ({size}, provider {w.images.name})"


def t_prod(w, a):
    return _j(w.payments.create_product(a["name"], a.get("description", "")))


def t_price(w, a):
    return _j(w.payments.create_price(a["product_id"], int(a["unit_amount"]), a.get("currency", "usd"), a.get("interval"), a.get("nickname", "")))


def t_price_upd(w, a):
    return _j(w.payments.update_price(a["price_id"], bool(a["active"])))


def t_pay_list(w, a):
    return _j({"catalog": w.payments.catalog(), "payments": w.payments.payments()[-20:]})


def t_ads_int(w, a):
    return _j(w.ads.search_interests(a["query"]))


def t_ads_loc(w, a):
    return _j(w.ads.search_locations(a["query"]))


def t_ads_camp(w, a):
    return _j(w.ads.create_campaign(a["name"], a["objective"], a.get("daily_budget"), a.get("lifetime_budget"), a.get("special_ad_category", "none")))


def t_ads_set(w, a):
    return _j(w.ads.create_ad_set(a["campaign_id"], a["name"], a["targeting"], a.get("daily_budget"), a.get("optimization_goal", "link_clicks")))


def t_ads_ad(w, a):
    return _j(w.ads.create_ad(a["ad_set_id"], a["name"], a["creative"]))


def t_ads_upd(w, a):
    return _j(w.ads.update(a["object_id"], a["changes"]))


def t_ads_over(w, a):
    return _j(w.ads.overview())


def t_sup_search(w, a):
    res = w.suppliers.search(a.get("query", ""), a.get("family", ""))
    return _j({"families": w.suppliers.families(), "results": res}) if res else _j({"families": w.suppliers.families(), "results": []})


def t_sup_quote(w, a):
    return _j(w.suppliers.quote(a["sku"], int(a["quantity"]), a["destination"]))


def t_sup_sample(w, a):
    return _j(w.suppliers.order_sample(a["sku"]))


def t_sup_order(w, a):
    return _j(w.suppliers.place_order(a["sku"], int(a["quantity"]), a["destination"], a.get("notes", "")))


def t_search(w, a):
    return _j(w.research.search(a["query"]))


def t_fetch(w, a):
    return _j(w.research.fetch(a["url"]))


def t_notes_read(w, a):
    return w.ws.read(NOTES) if w.ws.exists(NOTES) else "(no notes yet)"


def t_notes_write(w, a):
    old = w.ws.read(NOTES, max_chars=10**7) if w.ws.exists(NOTES) and a.get("mode", "append") == "append" else ""
    w.ws.write(NOTES, (old + "\n" if old else "") + a["content"])
    return "notes saved"


def t_status(w, a):
    plat = w.hosting.platform.state
    return _j({
        "week": w.week(), "simulated_weeks": w.task.episode.simulated_weeks,
        "cash_balance": w.ledger.balance, "ledger_totals": w.ledger.totals(),
        "deployed_version": w.hosting.version, "preview_url": w.hosting.server.url if w.hosting.server else None,
        "form_submissions": len(plat["forms"]), "payments": len(w.payments.payments()),
        "inventory_on_hand": w.suppliers.inventory(), "inventory_incoming": w.suppliers.incoming(),
        "active_ads": len(w.ads.active_ads()),
    })


def t_inbox(w, a):
    forms = w.hosting.platform.state["forms"]
    new = [f for f in forms[w.inbox_cursor:] if f.get("source", "").startswith("sim-persona")]
    w.inbox_cursor = len(forms)
    w.save_clock()
    pays = [p for p in w.payments.payments() if p.get("source", "").startswith("sim-persona")]
    samples = w.suppliers.samples_ready()
    return _j({"new_form_submissions": new[-30:], "recent_payments": pays[-10:], "sample_reports": samples})


TOOLS: list[Tool] = [
    Tool("shell", "Run a shell command in your sandboxed workspace (no internet access). Use it to build, test or inspect files.",
         {"command": S, "timeout_s": I}, ["command"], t_shell),
    Tool("write_file", "Create or overwrite a text file in the workspace.", {"path": S, "content": S}, ["path", "content"], t_write),
    Tool("read_file", "Read a text file from the workspace.", {"path": S}, ["path"], t_read),
    Tool("list_files", "List files under a workspace directory.", {"path": S}, [], t_list),
    Tool("deploy_site", "Deploy a static site directory (default 'site', must contain index.html) to the live preview host. "
         "Forms POST to /api/forms/<name>; checkout POSTs price_id (and optional quantity, success_url) to /api/checkout; "
         "GET /api/prices lists prices; /api/kv/<key> stores small JSON values.", {"directory": S}, [], t_deploy),
    Tool("view_page", "Load a page of your deployed site in a real browser and return its text, links, forms, prices and console errors.",
         {"path": S, "viewport": {"type": "string", "enum": ["desktop", "mobile"]}}, [], t_view),
    Tool("generate_image", "Generate an image (product shots, ad creatives, hero images). Saved to assets/<filename>.png and site/assets/<filename>.png.",
         {"prompt": S, "filename": S, "size": {"type": "string", "enum": ["square", "portrait", "landscape", "hero"]}}, ["prompt", "filename"], t_image),
    Tool("payments_create_product", "Create a product in the payments service (test mode).", {"name": S, "description": S}, ["name"], t_prod),
    Tool("payments_create_price", "Create a price for a product. unit_amount is in minor units (cents). Optional interval week|month|year for subscriptions.",
         {"product_id": S, "unit_amount": I, "currency": S, "interval": S, "nickname": S}, ["product_id", "unit_amount"], t_price),
    Tool("payments_update_price", "Activate or deactivate a price.", {"price_id": S, "active": {"type": "boolean"}}, ["price_id", "active"], t_price_upd),
    Tool("payments_list", "List products, prices and recent test payments.", {}, [], t_pay_list),
    Tool("ads_search_interests", "Search the ad platform's interest taxonomy; use returned ids in targeting.interests.", {"query": S}, ["query"], t_ads_int),
    Tool("ads_search_locations", "Search targetable locations (countries, regions, cities, neighborhoods); use returned keys in targeting.geo.locations.",
         {"query": S}, ["query"], t_ads_loc),
    Tool("ads_create_campaign", "Create a campaign. objective: awareness|traffic|leads|sales. Set daily_budget or lifetime_budget (USD) for campaign "
         "budgeting, or neither to budget per ad set. special_ad_category: none|housing|employment|credit.",
         {"name": S, "objective": S, "daily_budget": N, "lifetime_budget": N, "special_ad_category": S}, ["name", "objective"], t_ads_camp),
    Tool("ads_create_ad_set", "Create an ad set with targeting: {geo:{countries:[], locations:[keys], zips:['US:94122'], radius_km}, age_min, age_max, "
         "genders:['all'|'female'|'male'], languages:[], interests:[ids], exclude_interests:[ids], devices:['mobile','desktop']}. "
         "optimization_goal: impressions|link_clicks|leads|conversions.",
         {"campaign_id": S, "name": S, "targeting": O, "daily_budget": N, "optimization_goal": S}, ["campaign_id", "name", "targeting"], t_ads_set),
    Tool("ads_create_ad", "Create an ad. creative: {headline (<=40 chars), primary_text (<=125 recommended, 500 max), description (<=30), "
         "cta: LEARN_MORE|SHOP_NOW|BOOK_NOW|SIGN_UP|CONTACT_US|GET_QUOTE|SUBSCRIBE|DOWNLOAD|ORDER_NOW|APPLY_NOW, image_path (workspace PNG/JPG, "
         "ratio 1:1, 4:5, 1.91:1 or 9:16, >=600px wide), landing_path ('/...' on your site)}.",
         {"ad_set_id": S, "name": S, "creative": O}, ["ad_set_id", "name", "creative"], t_ads_ad),
    Tool("ads_update", "Update a campaign, ad set or ad by id. changes may include status (active|paused), budgets, targeting, creative, name.",
         {"object_id": S, "changes": O}, ["object_id", "changes"], t_ads_upd),
    Tool("ads_overview", "List all campaigns, ad sets and ads with status and spend.", {}, [], t_ads_over),
    Tool("suppliers_search", "Search the supplier catalog by keywords and/or family. Shows MOQ, price breaks, lead time, ratings, certifications.",
         {"query": S, "family": S}, [], t_sup_search),
    Tool("suppliers_quote", "Get a landed-cost quote. destination: US|EU|UK|AU|other.", {"sku": S, "quantity": I, "destination": S},
         ["sku", "quantity", "destination"], t_sup_quote),
    Tool("suppliers_order_sample", "Order a sample (costs simulated cash; report arrives in a later week via read_inbox).", {"sku": S}, ["sku"], t_sup_sample),
    Tool("suppliers_place_order", "Place a production order (charges simulated cash now; stock arrives after production + transit).",
         {"sku": S, "quantity": I, "destination": S, "notes": S}, ["sku", "quantity", "destination"], t_sup_order),
    Tool("web_search", "Search the web for market research (may be an offline research corpus).", {"query": S}, ["query"], t_search),
    Tool("fetch_url", "Fetch a URL returned by web_search.", {"url": S}, ["url"], t_fetch),
    Tool("notes_read", "Read your persistent NOTES.md (survives context summarization).", {}, [], t_notes_read),
    Tool("notes_write", "Append to (mode=append, default) or replace (mode=replace) your persistent NOTES.md.",
         {"content": S, "mode": {"type": "string", "enum": ["append", "replace"]}}, ["content"], t_notes_write),
    Tool("get_status", "Current simulated week, cash, ledger, deployment, inventory and ad status.", {}, [], t_status),
    Tool("read_inbox", "New customer form submissions, payments and supplier sample reports since you last checked.", {}, [], t_inbox),
    Tool("end_week", "End the current simulated week: the market runs your live ads and site, and you get the week's results and customer feedback.",
         {}, [], lambda w, a: "handled by harness"),
    Tool("finish", "Declare the business launched and end the episode early. Remaining simulated weeks still run with your final setup.",
         {"summary": S}, ["summary"], lambda w, a: "handled by harness"),
]
TOOL_MAP = {t.name: t for t in TOOLS}
EXPECTED_ERRORS = (AdsError, PaymentsError, SupplierError, WorkspaceError, ValueError, KeyError, TypeError)


def run_tool(world, name: str, args: dict) -> tuple[str, bool]:
    """Execute a tool; returns (output, is_error). Expected failures become readable errors for the model."""
    tool = TOOL_MAP.get(name)
    if not tool:
        return f"ERROR: unknown tool '{name}'", True
    missing = [r for r in tool.required if r not in (args or {})]
    if missing:
        return f"ERROR: missing required argument(s): {', '.join(missing)}", True
    try:
        return tool.fn(world, args or {}), False
    except EXPECTED_ERRORS as e:
        return f"ERROR: {e}", True
    except Exception as e:  # unexpected: surface but keep the episode alive
        return f"ERROR (internal): {type(e).__name__}: {e}", True


__all__ = ["TOOLS", "TOOL_MAP", "run_tool", "render_report", "TOOLSET_VERSION"]
