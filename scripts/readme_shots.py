"""Take the screenshots used in the README (needs `shingle up` running).

Usage: uv run python scripts/readme_shots.py
"""
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

APP, SITE, OUT = "http://localhost:8000", "http://localhost:8080", Path("docs/img")
OUT.mkdir(parents=True, exist_ok=True)


def shot(page, name, url=None, full=False):
    if url:
        page.goto(url, wait_until="networkidle")
    p = OUT / f"{name}.png"
    page.screenshot(path=str(p), full_page=full)
    Image.open(p).convert("RGB").quantize(256).save(p, optimize=True)  # keep the repo light


def login(page, user, pw):
    page.goto(APP + "/login")
    page.fill("input[name=username]", user)
    page.fill("input[name=password]", pw)
    page.click("button[type=submit]")
    page.wait_for_url(APP + "/")


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1280, "height": 800})
    shot(page, "site-home", SITE + "/")
    shot(page, "site-leaderboard", SITE + "/leaderboard.html")
    page.goto(SITE + "/showcase.html")
    shot(page, "site-case", SITE + page.locator("a.case-card").first.get_attribute("href"))
    # a business the diligent mock built, as graders see it (frozen, on its own origin)
    shot(page, "built-business", "http://b-73e77b.localhost:8000/")

    login(page, "grader1", "grader")
    rows = [(r.inner_text(), r.locator("a").first.get_attribute("href")) for r in page.locator("table tr").all()[1:]]
    for kind in ("absolute", "pairwise"):
        shot(page, f"grade-{kind}", APP + next(h for t, h in rows if kind in t))
    page.goto(APP + "/logout")

    login(page, "admin", "admin")
    shot(page, "admin", APP + "/admin")
    shot(page, "dashboard", APP + "/dashboard")
    run = page.locator("table a[href^='/dashboard/run/']").first.get_attribute("href")
    shot(page, "trajectory", APP + run + "/trajectory")
    b.close()
print("\n".join(f"{f.name} {f.stat().st_size // 1024} KB" for f in sorted(OUT.glob("*.png"))))
