"""Drive the grading app like a grader: log in, grade one absolute and one pairwise item, screenshot key pages.

Usage: uv run python scripts/ui_smoke.py http://localhost:8765 var/shots
"""
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

base, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)


def grade_absolute(page):
    for fs in page.locator("fieldset.dim").all():
        fs.locator("label").nth(4).click()  # score 5
    page.locator("input[name=acceptable][value=yes]").check()
    page.fill("textarea[name=rationale]", "Clear offer and working booking flow; targeting is local; honest copy.")


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 1000})
    page.goto(base + "/login")
    page.fill("input[name=username]", "grader1")
    page.fill("input[name=password]", "grader")
    page.click("button[type=submit]")
    page.wait_for_url(base + "/")
    page.screenshot(path=str(out / "queue.png"))
    assert "Your grading queue" in page.content()
    assert not re.search(r"mock-(diligent|hasty)", page.content()), "model identity leaked in queue"
    # find an absolute and a pairwise item
    rows = page.locator("table tr").all()[1:]
    abs_link = next(r.locator("a").first.get_attribute("href") for r in rows if "absolute" in r.inner_text())
    pair_link = next(r.locator("a").first.get_attribute("href") for r in rows if "pairwise" in r.inner_text())
    page.goto(base + abs_link)
    html = page.content()
    assert not re.search(r"mock-(diligent|hasty)|claude|openai", html, re.I), "model identity leaked in grading page"
    page.screenshot(path=str(out / "grade_absolute.png"), full_page=False)
    frame = page.frame_locator("iframe.site")
    frame.locator("body").wait_for(timeout=10000)
    print("iframe text:", frame.locator("body").inner_text()[:80].replace("\n", " "))
    page.locator("button[data-tab^=shots]").click()
    page.screenshot(path=str(out / "grade_absolute_shots.png"))
    grade_absolute(page)
    page.locator("form.card button[type=submit]").click()
    page.wait_for_load_state("load")
    page.goto(base + pair_link)
    page.screenshot(path=str(out / "grade_pairwise.png"))
    for d in page.locator("input[value=left]").all():
        d.check()
    page.fill("textarea[name=rationale]", "Left has working checkout and honest claims; right has fake reviews.")
    page.locator("form.card button[type=submit]").last.click()
    page.wait_for_load_state("load")
    page.goto(base + "/")
    done = page.locator("text=done").count()
    print("done chips on queue:", done)
    page.goto(base + "/logout")
    page.fill("input[name=username]", "admin")
    page.fill("input[name=password]", "admin")
    page.click("button[type=submit]")
    page.wait_for_url(base + "/")
    for name, path in [("admin", "/admin"), ("dashboard", "/dashboard")]:
        page.goto(base + path)
        page.screenshot(path=str(out / f"{name}.png"), full_page=True)
    run_href = page.locator("table a[href^='/dashboard/run/']").first.get_attribute("href")
    page.goto(base + run_href)
    page.screenshot(path=str(out / "run.png"), full_page=False)
    page.goto(base + run_href + "/trajectory")
    page.screenshot(path=str(out / "trajectory.png"), full_page=False)
    b.close()
print("ok")
