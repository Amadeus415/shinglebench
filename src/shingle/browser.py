"""Headless Chromium helpers shared by view_page, the market simulator, checks and QA."""

from __future__ import annotations

import re
from contextlib import contextmanager

from playwright.sync_api import Page, sync_playwright

DESKTOP = {"width": 1366, "height": 900}
MOBILE = {"width": 390, "height": 844}
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
             "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
PRICE_RE = re.compile(r"(?:[$€£₹₦]|USD|EUR|GBP|MXN|KES|NGN|INR|AUD|KSh|R\$)\s?\d[\d,.]*|\d[\d,.]*\s?(?:€|EUR|MXN|KES|NGN|INR|AUD|GBP)")


@contextmanager
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--disable-gpu"])
        try:
            yield b
        finally:
            b.close()


def new_page(b, mobile: bool = False, source: str = "harness") -> tuple[Page, list[str]]:
    ctx = b.new_context(viewport=MOBILE if mobile else DESKTOP, user_agent=MOBILE_UA if mobile else None,
                        is_mobile=mobile, has_touch=mobile, extra_http_headers={"X-Shingle-Source": source})
    page = ctx.new_page()
    errors: list[str] = []
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}"[:300]) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"[:300]))
    page.set_default_timeout(8000)
    return page, errors


SNAPSHOT_JS = """() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const links = [...document.querySelectorAll('a[href]')].map(a => ({text: (a.innerText||a.getAttribute('aria-label')||'').trim().slice(0,80), href: a.getAttribute('href')}));
  const forms = [...document.querySelectorAll('form')].map(f => ({action: f.getAttribute('action')||'', method: (f.getAttribute('method')||'get').toLowerCase(),
     fields: [...f.querySelectorAll('input,select,textarea')].filter(i => i.type !== 'hidden').map(i => ({name: i.name||i.id||'', type: i.type||i.tagName.toLowerCase(), required: i.required, label: (i.labels && i.labels[0] ? i.labels[0].innerText : i.placeholder||'').trim().slice(0,60)}))}));
  const buttons = [...document.querySelectorAll('button, input[type=submit], a.button, a.btn, [role=button]')].filter(vis).map(b => (b.innerText||b.value||'').trim().slice(0,60)).filter(Boolean);
  const imgs = [...document.images].map(i => ({src: i.getAttribute('src'), alt: i.getAttribute('alt'), w: i.naturalWidth}));
  const meta = n => (document.querySelector(`meta[name="${n}"]`)||{}).content || null;
  return {title: document.title, lang: document.documentElement.lang || null, text: document.body ? document.body.innerText : '',
    h1: [...document.querySelectorAll('h1')].map(h => h.innerText.trim()), links, forms, buttons, images: imgs,
    viewport_meta: meta('viewport'), description: meta('description'),
    overflow_x: document.documentElement.scrollWidth > window.innerWidth + 2,
    above_fold: document.body ? document.body.innerText.slice(0, 600) : ''};
}"""


def snapshot(page: Page) -> dict:
    snap = page.evaluate(SNAPSHOT_JS)
    snap["prices"] = sorted(set(PRICE_RE.findall(snap["text"])))[:20]
    snap["url"] = page.url
    return snap


def render_snapshot(snap: dict, errors: list[str], max_text: int = 5000) -> str:
    text = snap["text"]
    if len(text) > max_text:
        text = text[:max_text] + f"\n…[{len(snap['text'])} chars]"
    forms = "; ".join(f"{f['method'].upper()} {f['action'] or '(no action)'} fields=[{', '.join(x['name'] or x['type'] for x in f['fields'])}]" for f in snap["forms"]) or "none"
    links = ", ".join(f"{l['text'] or '?'} -> {l['href']}" for l in snap["links"][:40]) or "none"
    return (f"URL: {snap['url']}\nTITLE: {snap['title']}\nLANG: {snap['lang']}\nMETA viewport: {snap['viewport_meta']}  description: {snap['description']}\n"
            f"HORIZONTAL OVERFLOW: {snap['overflow_x']}\nH1: {snap['h1']}\nPRICES SEEN: {snap['prices']}\nFORMS: {forms}\nLINKS: {links}\n"
            f"CONSOLE ERRORS: {errors[:10] or 'none'}\n--- visible text ---\n{text}")


def navigate(page: Page, action, timeout: int = 6000) -> bool:
    """Run an action that may navigate; wait for the new page if it does. Returns True on navigation."""
    try:
        with page.expect_navigation(wait_until="load", timeout=timeout):
            action()
        return True
    except Exception:
        try:
            page.wait_for_load_state("load", timeout=2000)
        except Exception:
            pass
        return False


def fill_form(page: Page, form_selector: str, values: dict[str, str]) -> int:
    """Fill every visible field in a form using name/type heuristics. Returns fields filled."""
    filled = 0
    for el in page.query_selector_all(f"{form_selector} input, {form_selector} textarea, {form_selector} select"):
        try:
            typ = (el.get_attribute("type") or el.evaluate("e => e.tagName.toLowerCase()")).lower()
            if typ in ("hidden", "submit", "button", "image", "reset", "file") or not el.is_visible():
                continue
            key = " ".join(filter(None, [el.get_attribute("name"), el.get_attribute("id"), el.get_attribute("placeholder"),
                                          el.get_attribute("autocomplete"), el.get_attribute("aria-label")])).lower()
            if typ == "select":
                opts = el.evaluate("e => [...e.options].map(o => o.value).filter(v => v)")
                if opts:
                    el.select_option(opts[min(1, len(opts) - 1)] if len(opts) > 1 else opts[0])
                    filled += 1
                continue
            if typ in ("checkbox", "radio"):
                el.check()
                filled += 1
                continue
            val = _pick(key, typ, values)
            el.fill(val)
            filled += 1
        except Exception:
            continue
    return filled


def _pick(key: str, typ: str, v: dict[str, str]) -> str:
    if typ == "email" or "mail" in key:
        return v.get("email", "test.customer@example.com")
    if typ == "tel" or "phone" in key or "tel" in key:
        return v.get("phone", "4155550123")
    if typ == "date" or "date" in key:
        return v.get("date", "2026-11-12")
    if typ == "time":
        return "10:00"
    if typ == "number":
        return v.get("number", "2")
    if "zip" in key or "postal" in key or "postcode" in key:
        return v.get("zip", "94122")
    if "name" in key:
        return v.get("name", "Test Customer")
    if "address" in key or "street" in key:
        return v.get("address", "1200 Test Ave")
    if "city" in key:
        return v.get("city", "San Francisco")
    if typ == "textarea" or "message" in key or "note" in key or "detail" in key or "issue" in key:
        return v.get("message", "Hi, I'm interested. Is this available next week?")
    return v.get("text", "Test")
