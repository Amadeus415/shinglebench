"""Browser checks over a frozen site: load, key pages, links, console, audits, mobile, forms, checkout."""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urljoin, urlparse

from ..browser import browser, fill_form, navigate, new_page

AUDIT_JS = """() => {
  const imgs=[...document.images]; const inputs=[...document.querySelectorAll('input,select,textarea')].filter(i=>!['hidden','submit','button'].includes(i.type));
  const labelled = i => (i.labels&&i.labels.length) || i.getAttribute('aria-label') || i.getAttribute('aria-labelledby') || i.title;
  const hs=[...document.querySelectorAll('h1,h2,h3,h4,h5,h6')].map(h=>+h.tagName[1]); let skip=0; for(let i=1;i<hs.length;i++) if(hs[i]-hs[i-1]>1) skip++;
  const links=[...document.querySelectorAll('a')]; const badLinks=links.filter(a=>!(a.innerText||a.getAttribute('aria-label')||a.querySelector('img[alt]'))).length;
  const small=[...document.querySelectorAll('a,button,input,select')].filter(e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&(r.height<24||r.width<24);}).length;
  const tinyText=[...document.querySelectorAll('p,li,a,span,td')].filter(e=>parseFloat(getComputedStyle(e).fontSize)<12&&e.innerText.trim()).length;
  const res=performance.getEntriesByType('resource'); const bytes=res.reduce((a,r)=>a+(r.transferSize||r.encodedBodySize||0),0);
  const nav=performance.getEntriesByType('navigation')[0]||{};
  const headScripts=[...document.head.querySelectorAll('script[src]:not([async]):not([defer])')].length;
  return {doctype: !!document.doctype, charset: !!document.querySelector('meta[charset]'), lang: !!document.documentElement.lang,
    title: !!document.title.trim(), description: !!document.querySelector('meta[name=description]'), viewport: !!document.querySelector('meta[name=viewport]'),
    h1: document.querySelectorAll('h1').length, img_total: imgs.length, img_no_alt: imgs.filter(i=>!i.hasAttribute('alt')).length,
    img_no_dims: imgs.filter(i=>!i.getAttribute('width')).length, inputs: inputs.length, inputs_unlabelled: inputs.filter(i=>!labelled(i)).length,
    heading_skips: skip, links_no_text: badLinks, small_targets: small, tiny_text: tinyText, requests: res.length, bytes: bytes + (nav.transferSize||0),
    load_ms: Math.round(nav.loadEventEnd||0), head_blocking_scripts: headScripts,
    overflow_x: document.documentElement.scrollWidth > window.innerWidth + 2};
}"""


def _score(pairs: list[tuple[bool, int]]) -> int:
    total = sum(w for _, w in pairs)
    return round(100 * sum(w for ok, w in pairs if ok) / total) if total else 0


def lite_scores(a: dict) -> dict:
    return {
        "performance": _score([(a["bytes"] < 1_500_000, 3), (a["requests"] < 40, 2), (a["load_ms"] < 2500, 3), (a["head_blocking_scripts"] == 0, 1), (a["img_no_dims"] == 0, 1)]),
        "accessibility": _score([(a["lang"], 2), (a["img_no_alt"] == 0, 3), (a["inputs_unlabelled"] == 0, 3), (a["heading_skips"] == 0, 1),
                                 (a["links_no_text"] == 0, 2), (a["h1"] >= 1, 1)]),
        "seo": _score([(a["title"], 3), (a["description"], 2), (a["viewport"], 2), (a["h1"] == 1, 1), (a["lang"], 1)]),
        "best_practices": _score([(a["doctype"], 2), (a["charset"], 1), (a.get("console_errors", 0) == 0, 3), (a["viewport"], 1)]),
    }


def lighthouse(url: str) -> dict | None:
    """Real Lighthouse when the CLI is installed (it is in the Docker image); otherwise None."""
    exe = shutil.which("lighthouse")
    if not exe:
        return None
    env = dict(os.environ)
    if "CHROME_PATH" not in env:  # use Playwright's Chromium
        found = sorted(glob.glob(os.path.join(env.get("PLAYWRIGHT_BROWSERS_PATH", os.path.expanduser("~/.cache/ms-playwright")), "chromium-*/chrome-linux*/chrome")))
        if found:
            env["CHROME_PATH"] = found[-1]
    with tempfile.NamedTemporaryFile(suffix=".json") as f:
        try:
            subprocess.run([exe, url, "--quiet", "--output=json", f"--output-path={f.name}", "--chrome-flags=--headless=new --no-sandbox",
                            "--only-categories=performance,accessibility,seo,best-practices"], check=True, timeout=180, capture_output=True, env=env)
            data = json.loads(open(f.name).read())
            return {k.replace("-", "_"): round((v.get("score") or 0) * 100) for k, v in data["categories"].items()}
        except Exception:
            return None


def run_site_checks(base_url: str, platform, task, pages: list[str]) -> dict:
    out: dict = {}
    results_pages = {}
    to_visit, seen, broken, external, console = list(pages), set(), [], set(), []
    audits = {}
    forms_found: list[tuple[str, int, str]] = []
    checkout_paths: list[str] = []
    with browser() as b:
        # crawl desktop
        while to_visit and len(seen) < 40:
            path = to_visit.pop(0)
            if path in seen:
                continue
            seen.add(path)
            page, errs = new_page(b, source="checks")
            try:
                t = time.time()
                r = page.goto(base_url + path, wait_until="load")
                status = r.status if r else 0
                results_pages[path] = {"status": status, "ms": round((time.time() - t) * 1000)}
                if status >= 400:
                    continue
                a = page.evaluate(AUDIT_JS)
                a["console_errors"] = len(errs)
                audits[path] = a
                console += [f"{path}: {e}" for e in errs]
                for i, f in enumerate(page.query_selector_all("form")):
                    action = f.get_attribute("action") or ""
                    if "/api/checkout" in action:
                        checkout_paths.append(path)
                    else:
                        forms_found.append((path, i, action))
                for href in page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))"):
                    if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                        continue
                    full = urljoin(base_url + path, href)
                    u = urlparse(full)
                    if u.netloc != urlparse(base_url).netloc:
                        external.add(full)
                        continue
                    target = u.path or "/"
                    if target not in seen and target not in to_visit and not target.startswith("/__checkout"):
                        if platform.handle("GET", target, {}, b"").status >= 400:
                            broken.append({"from": path, "href": href})
                            seen.add(target)
                        else:
                            to_visit.append(target)
            finally:
                page.context.close()

        home = results_pages.get("/", {})
        out["site_loads"] = {"status": "pass" if home.get("status") == 200 else "fail", "details": home}
        missing = [p for p in pages[1:] if results_pages.get(p, {}).get("status") != 200 and platform.handle("GET", p, {}, b"").status != 200]
        out["key_pages"] = {"status": "pass" if not missing else "fail", "missing": missing, "required": pages[1:]}
        out["links"] = {"status": "pass" if not broken else "fail", "pages_crawled": len(seen), "broken": broken[:30], "external": sorted(external)[:30]}
        out["console"] = {"status": "pass" if not console else "warn", "errors": console[:30]}

        # audits: Lighthouse if available, else lite audits (averaged over pages)
        lh = lighthouse(base_url + "/") if audits else None
        if audits:
            per = {p: lite_scores(a) for p, a in audits.items()}
            avg = {k: round(sum(s[k] for s in per.values()) / len(per)) for k in next(iter(per.values()))}
            out["lighthouse"] = {"status": "pass" if min(avg.values()) >= 70 else "warn", "engine": "lighthouse" if lh else "shingle-lite-audits",
                                 "scores": lh or avg, "lite_scores": avg, "per_page": per,
                                 "findings": {p: {k: v for k, v in a.items() if k in ("img_no_alt", "inputs_unlabelled", "heading_skips", "links_no_text", "bytes", "load_ms") and v} for p, a in audits.items()}}
        else:
            out["lighthouse"] = {"status": "skip", "reason": "no pages loaded"}

        # mobile rendering
        mob = {}
        for path in pages[:8]:
            page, _ = new_page(b, mobile=True, source="checks")
            try:
                r = page.goto(base_url + path, wait_until="load")
                if r and r.status == 200:
                    a = page.evaluate(AUDIT_JS)
                    mob[path] = {"overflow_x": a["overflow_x"], "viewport_meta": a["viewport"], "small_targets": a["small_targets"], "tiny_text": a["tiny_text"]}
            finally:
                page.context.close()
        bad = [p for p, m in mob.items() if m["overflow_x"] or not m["viewport_meta"]]
        out["mobile"] = {"status": "pass" if mob and not bad else ("fail" if bad else "skip"), "pages": mob, "problems": bad}

        # forms: submit each non-checkout form once
        form_results = []
        for path, idx, action in forms_found[:8]:
            page, errs = new_page(b, source="checks")
            try:
                page.goto(base_url + path, wait_until="load")
                before = len(platform.state["forms"])
                form = page.locator("form").nth(idx)
                tmp_id = f"shingle-form-{idx}"
                form.evaluate(f"(f) => f.id = f.id || '{tmp_id}'")
                fid = form.get_attribute("id")
                fill_form(page, f"#{fid}", {"name": "QA Tester", "email": "qa@checks.shingle.test", "zip": _zip(task), "message": "Automated check, please ignore."})
                btn = form.locator("button[type=submit], input[type=submit], button:not([type])").first
                navigate(page, (lambda: btn.click()) if btn.count() else (lambda: form.evaluate("f => f.requestSubmit()")))
                page.wait_for_timeout(250)
                stored = len(platform.state["forms"]) > before
                form_results.append({"page": path, "action": action, "stored": stored, "landed": page.url.replace(base_url, ""),
                                     "ok": stored or not action.startswith("/api/forms"), "console_errors": errs[:3]})
            except Exception as e:
                form_results.append({"page": path, "action": action, "ok": False, "error": str(e)[:200]})
            finally:
                page.context.close()
        out["forms"] = {"status": "skip" if not form_results else ("pass" if all(f["ok"] and f.get("stored", True) for f in form_results) else "fail"),
                        "forms": form_results}

        # checkout: complete once with the test card
        ck = {"status": "skip", "reason": "no checkout form found"}
        for path in dict.fromkeys(checkout_paths):
            page, errs = new_page(b, source="checks")
            try:
                page.goto(base_url + path, wait_until="load")
                before = len(platform.payments.payments())
                navigate(page, lambda: page.locator("form[action*='/api/checkout'] button, form[action*='/api/checkout'] input[type=submit]").first.click())
                if "/__checkout/" not in page.url:
                    ck = {"status": "fail", "page": path, "reason": f"checkout did not open (landed on {page.url.replace(base_url, '')})"}
                    continue
                page.fill("input[name=email]", "qa@checks.shingle.test")
                page.fill("input[name=card]", "4242 4242 4242 4242")
                navigate(page, lambda: page.click("button[type=submit]"))
                paid = len(platform.payments.payments()) > before
                ck = {"status": "pass" if paid else "fail", "page": path, "paid": paid, "landed": page.url.replace(base_url, ""),
                      "amount": platform.payments.payments()[-1]["amount"] if paid else None}
                break
            except Exception as e:
                ck = {"status": "fail", "page": path, "reason": str(e)[:200]}
            finally:
                page.context.close()
        out["checkout"] = ck
    return out


def _zip(task) -> str:
    m = task.market
    if m and m.country == "US" and m.neighborhood:
        from ..sandbox.ads import gazetteer

        for v in gazetteer().values():
            if v["type"] == "neighborhood" and v["name"] == m.neighborhood and v.get("zips"):
                return v["zips"][0]
    return "94122"
