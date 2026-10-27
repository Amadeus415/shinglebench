"""Screenshot every company-site page at desktop and mobile widths and check basic health.

Usage: uv run python scripts/site_shots.py http://localhost:8080 var/shots/site
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

base, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
pages = ["/", "/leaderboard.html", "/showcase.html", "/methodology.html", "/labs.html", "/blog/report-01.html"]
problems = []
with sync_playwright() as p:
    b = p.chromium.launch()
    for mode, vp in (("desktop", {"width": 1366, "height": 900}), ("mobile", {"width": 390, "height": 844})):
        ctx = b.new_context(viewport=vp, is_mobile=mode == "mobile")
        for path in pages:
            page = ctx.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            r = page.goto(base + path, wait_until="networkidle")
            if r.status != 200:
                problems.append(f"{path} -> {r.status}")
            if page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 2"):
                problems.append(f"{mode} {path}: horizontal overflow")
            broken = page.evaluate("[...document.images].filter(i => i.complete && i.naturalWidth === 0).map(i => i.src)")
            problems += [f"{path}: broken image {s}" for s in broken]
            problems += [f"{path}: js error {e}" for e in errors]
            name = (path.strip("/").replace("/", "_").replace(".html", "") or "home")
            page.screenshot(path=str(out / f"{mode}-{name}.png"), full_page=True)
            page.close()
        # follow one case-file link
        page = ctx.new_page()
        page.goto(base + "/showcase.html")
        href = page.locator("a.case-card").first.get_attribute("href")
        page.goto(base + href)
        page.screenshot(path=str(out / f"{mode}-case.png"), full_page=True)
        ctx.close()
    b.close()
print("\n".join(problems) or "no problems")
