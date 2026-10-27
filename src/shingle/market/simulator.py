"""Simulated market: a structured demand model plus personas that really browse the site.

Clearly a SECONDARY, SIMULATED signal. Per week:
 1. Each live ad set spends its budget (capped by cash and audience size) -> impressions.
 2. Targeting is scored against the task's hidden true audience -> share of in-market reach.
 3. Creatives are scored (heuristics, optionally an LLM persona rating) -> CTR.
 4. The live site is probed in headless Chromium (load, price, CTA, mobile, conversion path).
 5. A small panel of sampled personas actually visit, and those who decide to convert really
    submit the form / complete test checkout. Totals are extrapolated with the same model.
 6. Revenue, fees and ad spend post to the ledger; physical sales are capped by inventory.
All randomness is seeded by (task, seed, week). Every trace is written to state/market/.
"""

from __future__ import annotations

import json
import math
import re
import statistics
from pathlib import Path

from ..browser import browser, fill_form, navigate, new_page, snapshot
from ..sandbox.ads import gazetteer, haversine_km, slug
from .personas import sample_personas, stable_rng

CPM_USD = {"US": 9.0, "CA": 7.5, "GB": 7.0, "IE": 6.5, "DE": 7.0, "FR": 6.0, "NL": 6.5, "PT": 4.0, "ES": 4.5, "MX": 2.5,
           "AU": 8.0, "NZ": 6.0, "IN": 1.2, "NG": 1.0, "KE": 1.2, "ZA": 2.0, "SG": 6.0, "JP": 6.0, "EU": 5.5}
BASE_CTR = 0.016
OUT_MARKET_CTR = 0.0025
CONV_BASE = {"checkout": 0.08, "booking": 0.10, "inquiry": 0.12, "signup": 0.2}
PANEL = 40
BROWSE_N = 6


def _center(task) -> tuple[float, float] | None:
    m = task.market
    if m and m.lat is not None and m.lon is not None:
        return (m.lat, m.lon)
    if m and m.city:
        g = gazetteer().get(f"city:{m.country}:{slug(m.city)}")
        if g and g.get("lat") is not None:
            return (g["lat"], g["lon"])
    return None


def targeting_fit(task, targeting: dict) -> dict:
    """Precision (share of reach in the true audience) and coverage (share of audience reachable)."""
    gz = gazetteer()
    geo = targeting["geo"]
    m = task.market
    country = m.country if m else "US"
    center = _center(task)
    radius = (m.service_radius_km if m else None)
    p_geo, c_geo = 0.05, 0.1
    locs = [gz[k] for k in geo.get("locations", []) if k in gz]
    zips = [z.split(":", 1)[1] for z in geo.get("zips", []) if z.startswith(f"{country}:")]
    if radius and center:  # local market: precision falls as targeted area grows past the service area
        best = 0.0
        for loc in locs:
            if loc.get("lat") is None:
                if loc["type"] in ("country", "region") and loc.get("country") == country:
                    best = max(best, 0.03 if loc["type"] == "country" else 0.08)
                continue
            d = haversine_km(center, (loc["lat"], loc["lon"]))
            r = geo.get("radius_km") or (3.0 if loc["type"] == "neighborhood" else 12.0)
            if d <= radius + r:
                best = max(best, min(1.0, (radius / max(r, radius)) ** 2) * (1.0 if d <= radius else 0.5))
        task_zips = set()
        for v in gz.values():
            if v["type"] == "neighborhood" and v.get("lat") is not None and center and haversine_km(center, (v["lat"], v["lon"])) <= radius + 1:
                task_zips.update(v.get("zips", []))
        if zips:
            hit = len([z for z in zips if z in task_zips])
            if hit:
                best = max(best, 0.6 + 0.4 * hit / len(zips))
                c_geo = max(c_geo, min(1.0, hit / max(1, len(task_zips))))
        if country in geo.get("countries", []):
            best = max(best, 0.02)
        p_geo = best or 0.01
        c_geo = max(c_geo, 1.0 if best >= 0.25 else best * 3)
    else:  # city / national market
        cities_in = [l for l in locs if l.get("country") == country and l["type"] in ("city", "neighborhood")]
        if country in geo.get("countries", []) or any(l["type"] == "region" and l.get("country") in (country, "EU") for l in locs):
            p_geo, c_geo = 0.7, 1.0
        if m and m.city and center:
            near = [l for l in cities_in if l.get("lat") is not None and haversine_km(center, (l["lat"], l["lon"])) < 40]
            if near:
                p_geo, c_geo = 0.95, 1.0
            elif country in geo.get("countries", []):
                p_geo = 0.15
        elif cities_in:
            p_geo, c_geo = 0.95, min(1.0, 0.35 + 0.15 * len(cities_in))
        if zips:
            p_geo, c_geo = max(p_geo, 0.8), max(c_geo, 0.3)
    lo, hi = task.sim.age_range
    a, b = targeting.get("age_min", 18), targeting.get("age_max", 65)
    overlap = max(0, min(hi, b) - max(lo, a))
    p_age = overlap / max(1, b - a)
    c_age = overlap / max(1, hi - lo)
    rel = set(task.sim.relevant_interests)
    ints = set(targeting.get("interests", []))
    if not ints:
        p_int, c_int = 0.3, 1.0
    else:
        hits = len(ints & rel)
        p_int = 0.2 + 0.8 * hits / len(ints) if rel else 0.4
        c_int = min(1.0, 0.25 + 0.75 * hits / max(1, min(3, len(rel))))
    precision = max(0.01, p_geo * (0.35 + 0.65 * p_age) * p_int)
    coverage = max(0.01, c_geo * c_age * c_int)
    return {"precision": round(precision, 3), "coverage": round(coverage, 3), "geo": round(p_geo, 3),
            "age": round(p_age, 3), "interests": round(p_int, 3)}


SPAM = re.compile(r"!!|#1|\bbest\b|\bguaranteed?\b|\bmiracle\b|\bfree money\b|\bact now\b", re.I)


def creative_score(task, creative: dict) -> tuple[float, list[str]]:
    h, t = creative["headline"], creative["primary_text"]
    s, notes = 1.0, []
    if 15 <= len(h) <= 40:
        s += 0.1
    if re.search(r"\d|[$€£₹₦]", h + " " + t):
        s += 0.12
    else:
        notes.append("no concrete number or price in the ad")
    m = task.market
    place_words = [w for w in ([m.city, m.neighborhood] if m else []) if w] + (re.findall(r"[A-Z][a-z]+", m.region)[:4] if m else [])
    if m and m.service_radius_km:
        if any(w.lower() in (h + t).lower() for w in place_words):
            s += 0.2
        else:
            notes.append("ad doesn't say where the service is")
    if SPAM.search(h + " " + t):
        s -= 0.25
        notes.append("hype language reduces trust")
    if len(t) > 125:
        s -= 0.08
    if len(t) < 30:
        s -= 0.1
        notes.append("primary text is too thin to explain the offer")
    cta_fit = {"checkout": {"SHOP_NOW", "ORDER_NOW", "DOWNLOAD", "SIGN_UP", "LEARN_MORE"},
               "booking": {"BOOK_NOW", "GET_QUOTE", "CONTACT_US", "LEARN_MORE"},
               "inquiry": {"CONTACT_US", "GET_QUOTE", "LEARN_MORE", "BOOK_NOW"},
               "signup": {"SIGN_UP", "SUBSCRIBE", "LEARN_MORE", "DOWNLOAD"}}.get(task.sim.conversion or "checkout", set())
    if creative["cta"] not in cta_fit:
        s -= 0.1
        notes.append(f"CTA {creative['cta']} doesn't match the offer")
    return max(0.3, min(1.6, s)), notes


def _price_from(text_prices: list[str], ref: float) -> float | None:
    vals = []
    for p in text_prices:
        n = re.sub(r"[^\d.]", "", p.replace(",", ""))
        try:
            v = float(n)
        except ValueError:
            continue
        if ref / 8 <= v <= ref * 8:
            vals.append(v)
    return statistics.median(vals) if vals else None


def price_fit(price: float | None, wtp: float, ref: float) -> float:
    if price is None:
        return 0.55  # no visible price: many people won't commit
    return 1 / (1 + math.exp((price - wtp) / (0.18 * ref)))


class Market:
    def __init__(self, world, llm=None):
        self.w = world
        self.llm = llm  # optional persona model for ratings / quotes (see market/llm.py)
        self.dir = world.state_dir / "market"
        self.dir.mkdir(parents=True, exist_ok=True)

    # -------------------------------------------------------------- site probe
    def probe_site(self, landing_paths: list[str]) -> dict:
        task = self.w.task
        url = self.w.hosting.server.url if self.w.hosting.server else None
        if not url or not self.w.hosting.current_dir:
            return {"loads": False, "score": 0.0, "issues": ["site is not deployed"], "pages": {}}
        out = {"loads": True, "issues": [], "pages": {}}
        with browser() as b:
            for path in sorted(set(landing_paths or ["/"])):
                for mobile in (False, True):
                    page, errs = new_page(b, mobile=mobile, source="sim-probe")
                    try:
                        resp = page.goto(url + path, wait_until="load")
                        snap = snapshot(page)
                        out["pages"][f"{path}|{'m' if mobile else 'd'}"] = {
                            "status": resp.status if resp else 0, "prices": snap["prices"], "h1": snap["h1"][:2],
                            "forms": len(snap["forms"]), "overflow": snap["overflow_x"], "errors": errs[:5],
                            "words": len(snap["text"].split()),
                            "cta": [x for x in snap["buttons"] + [l["text"] for l in snap["links"]]
                                    if re.search(r"book|buy|shop|order|get|start|sign|subscribe|unlock|pay|checkout|contact|quote|reserv|agend|compr|kaufen|buchen", x, re.I)][:6],
                            "links": [l["href"] for l in snap["links"]][:60],
                        }
                    except Exception as e:
                        out["pages"][f"{path}|{'m' if mobile else 'd'}"] = {"status": 0, "error": str(e)[:200]}
                    finally:
                        page.context.close()
        ok_pages = [p for p in out["pages"].values() if p.get("status") == 200]
        if not ok_pages:
            out.update(loads=False, score=0.0)
            out["issues"].append("landing page failed to load")
            return out
        score = 1.0
        prices = [x for p in ok_pages for x in p["prices"]]
        if not prices:
            score -= 0.15
            out["issues"].append("no price visible on the landing page")
        if not any(p["cta"] for p in ok_pages):
            score -= 0.2
            out["issues"].append("no clear call to action")
        if any(p["overflow"] for k, p in out["pages"].items() if k.endswith("|m") and p.get("status") == 200):
            score -= 0.15
            out["issues"].append("layout breaks on mobile (horizontal scroll)")
        if any(p["errors"] for p in ok_pages):
            score -= 0.05
            out["issues"].append("JavaScript errors on page")
        if all(p["words"] < 60 for p in ok_pages):
            score -= 0.15
            out["issues"].append("landing page explains very little")
        site = self.w.hosting.current_dir
        for need, label in (("privacy", "privacy page"), ("faq", "FAQ"), ("contact", "contact page")):
            if not any(need in str(p).lower() for p in site.rglob("*.html")):
                score -= 0.03
        out["score"] = round(max(0.05, score), 3)
        out["text_price"] = _price_from(prices, task.sim.reference_price or 30)
        return out

    # -------------------------------------------------------------- one visit
    def _visit(self, b, url: str, landing: str, persona: dict, convert: bool, kind: str) -> dict:
        trace = {"persona": persona["id"], "landing": landing, "device": persona["device"], "steps": [], "converted": False}
        page, errs = new_page(b, mobile=persona["device"] == "mobile", source=f"sim-persona:{persona['id']}")
        try:
            page.goto(url + landing, wait_until="load")
            trace["steps"].append(f"landed on {landing}")
            if not convert:
                trace["steps"].append("browsed and left")
                return trace
            values = {"name": f"{persona['name']} (simulated)", "email": f"{persona['id']}@sim.shingle.test",
                      "message": "Hi, I'd like to book this. Is next week possible?"}
            if kind == "checkout":
                ok = self._try_checkout(page, url, values, trace)
            else:
                ok = self._try_form(page, url, values, trace)
            trace["converted"] = ok
            if not ok:
                trace["failure"] = trace["steps"][-1]
        except Exception as e:
            trace["steps"].append(f"error: {str(e)[:160]}")
            trace["failure"] = "page error"
        finally:
            trace["console_errors"] = errs[:5]
            page.context.close()
        return trace

    def _follow(self, page, url: str, pattern: str, trace: dict) -> bool:
        before = page.url
        for el in page.query_selector_all("a[href], button"):
            try:
                txt = (el.inner_text() or "") + " " + (el.get_attribute("href") or "")
                if el.is_visible() and re.search(pattern, txt, re.I):
                    href = el.get_attribute("href") or ""
                    if href and (url + href if href.startswith("/") else href).rstrip("/") == before.rstrip("/"):
                        continue  # link to the current page
                    navigate(page, el.click)
                    trace["steps"].append(f"clicked '{txt.strip()[:40]}' -> {page.url.replace(url, '')}")
                    return True
            except Exception:
                continue
        return False

    def _try_checkout(self, page, url: str, values: dict, trace: dict) -> bool:
        for _ in range(3):
            if "/__checkout/" in page.url:
                break
            # a form posting to /api/checkout, or a link/button that leads there
            form = page.query_selector("form[action*='/api/checkout']")
            if form:
                btn = form.query_selector("button, input[type=submit]")
                navigate(page, btn.click if btn else lambda: form.evaluate("f => f.requestSubmit ? f.requestSubmit() : f.submit()"))
                trace["steps"].append("submitted checkout form")
                continue
            if not self._follow(page, url, r"buy|checkout|unlock|order|add to cart|get it|purchase|pay|shop|pricing|comprar|kaufen", trace):
                trace["steps"].append("could not find a way to buy")
                return False
        if "/__checkout/" not in page.url:
            trace["steps"].append("never reached checkout")
            return False
        page.fill("input[name=email]", values["email"])
        page.fill("input[name=card]", "4242 4242 4242 4242")
        navigate(page, lambda: page.click("button[type=submit]"))
        ok = "complete" in page.content().lower() or "/__checkout/" not in page.url
        trace["steps"].append("paid in test checkout" if ok else "payment failed")
        return ok

    def _try_form(self, page, url: str, values: dict, trace: dict) -> bool:
        before = len(self.w.hosting.platform.state["forms"])
        if not page.query_selector("form"):
            if not self._follow(page, url, r"book|schedule|contact|quote|enquir|inquir|sign up|join|subscribe|apply|reserv|agend|buchen|start", trace):
                trace["steps"].append("could not find a booking or contact form")
                return False
        form = page.query_selector("form")
        if not form:
            trace["steps"].append("no form on the page")
            return False
        n = fill_form(page, "form", values)
        trace["steps"].append(f"filled {n} fields")
        btn = page.query_selector("form button[type=submit], form input[type=submit], form button:not([type])")
        navigate(page, btn.click if btn else lambda: form.evaluate("f => f.requestSubmit ? f.requestSubmit() : f.submit()"))
        page.wait_for_timeout(200)
        ok = len(self.w.hosting.platform.state["forms"]) > before
        trace["steps"].append("submitted form" if ok else "form submission did not go through")
        return ok

    # -------------------------------------------------------------- the week
    def run_week(self) -> dict:
        w, task = self.w, self.w.task
        week = w.week()
        rng = stable_rng("market", task.id, w.seed, week)
        ref = task.sim.reference_price or 30.0
        kind = task.sim.conversion or ("checkout" if "checkout" in [d.value for d in task.deliverables] else "inquiry")
        country = task.market.country if task.market else "US"
        cpm_base = CPM_USD.get(country, 4.0) * math.exp(rng.gauss(0, 0.15))
        ads = w.ads.active_ads()
        budgets = w.ads.weekly_budgets()
        landing_paths = sorted({a["creative"]["landing_path"] for _, _, a in ads}) or ["/"]
        probe = self.probe_site(landing_paths)
        catalog = [p for p in w.payments.catalog() if p["active"]]
        cat_price = statistics.median([p["unit_amount"] / 100 for p in catalog]) if catalog else None
        price = cat_price if kind == "checkout" else (probe.get("text_price") or cat_price)
        conv_possible = probe["loads"] and (kind != "checkout" or bool(catalog))

        cash = max(0.0, w.ledger.balance)
        total_budget = sum(budgets.values())
        scale = min(1.0, cash / total_budget) if total_budget else 0.0
        rows, ad_sets_seen = [], {}
        for camp, aset, ad in ads:
            if aset["id"] not in ad_sets_seen:
                ad_sets_seen[aset["id"]] = (targeting_fit(task, aset["targeting"]), [a for _, s, a in ads if s["id"] == aset["id"]])
            fit, siblings = ad_sets_seen[aset["id"]]
            spend_cap = budgets.get(aset["id"], 0.0) * scale / max(1, len(siblings))
            narrow = 1 - fit["coverage"]
            cpm = cpm_base * (1 + 0.6 * narrow)
            audience = {"low": 30_000, "medium": 60_000, "high": 120_000}[task.sim.demand] * (
                1 if task.market and task.market.service_radius_km else 25) * fit["coverage"] / max(1, len(siblings))
            impressions = min(int(spend_cap / cpm * 1000), int(audience * 2.5))
            spend = round(impressions * cpm / 1000, 2)
            cscore, cnotes = creative_score(task, ad["creative"])
            if self.llm:
                cscore = self.llm.rate_creative(task, ad["creative"], cscore)
            ctr_in = BASE_CTR * cscore
            in_share = fit["precision"]
            clicks_mean = impressions * (in_share * ctr_in + (1 - in_share) * OUT_MARKET_CTR)
            clicks = int(max(0, rng.gauss(clicks_mean, math.sqrt(max(clicks_mean, 1)))))
            rows.append({"ad_id": ad["id"], "ad_name": ad["name"], "ad_set_id": aset["id"], "campaign_id": camp["id"],
                         "landing_path": ad["creative"]["landing_path"], "impressions": impressions, "clicks": clicks,
                         "spend": spend, "ctr": round(clicks / impressions, 4) if impressions else 0.0,
                         "cpc": round(spend / clicks, 2) if clicks else None, "fit": fit, "creative_score": round(cscore, 3),
                         "creative_notes": cnotes, "in_market_share": in_share})

        # personas reached through each ad's targeting
        clicks_total = sum(r["clicks"] for r in rows)
        in_share_w = (sum(r["in_market_share"] * r["clicks"] for r in rows) / clicks_total) if clicks_total else 0.3
        personas = sample_personas(task, w.seed, week, PANEL, in_market_share=min(0.95, in_share_w * 1.6))
        p_conv = []
        for p in personas:
            mobile_pen = 0.75 if p["device"] == "mobile" and "layout breaks on mobile (horizontal scroll)" in probe["issues"] else 1.0
            pc = CONV_BASE[kind] * p["intent"] * price_fit(price, p["wtp"], ref) * probe.get("score", 0) * mobile_pen
            p["p_convert"] = round(pc if conv_possible else 0.0, 4)
            p_conv.append(p["p_convert"])
        mean_pc = statistics.mean(p_conv) if p_conv else 0.0

        traces = []
        url = w.hosting.server.url if w.hosting.server else None
        if url and probe["loads"] and clicks_total:
            visitors = rng.sample(personas, k=min(BROWSE_N, len(personas)))
            with browser() as b:
                for p in visitors:
                    landing = rng.choice(landing_paths)
                    decide = rng.random() < min(0.95, p["p_convert"] * 6)  # panel is oversampled for converters
                    traces.append(self._visit(b, url, landing, p, decide, kind) | {"intended_to_convert": decide})
        attempted = [t for t in traces if t["intended_to_convert"]]
        broken = attempted and not any(t["converted"] for t in attempted)
        if broken:
            mean_pc *= 0.05  # the conversion path doesn't work for real visitors
        conversions = int(max(0, rng.gauss(clicks_total * mean_pc, math.sqrt(max(clicks_total * mean_pc, 0.5)))))
        if not conv_possible:
            conversions = 0
        inquiries = int(clicks_total * 0.02 * probe.get("score", 0)) if kind in ("checkout", "signup") else 0

        # fulfillment + money
        unfulfilled = preorders = 0
        if task.category.value == "physical_product":
            fulfilled = w.suppliers.record_sales(conversions)
            unfulfilled = conversions - fulfilled
            site_text = " ".join(p.read_text(errors="ignore").lower() for p in w.hosting.current_dir.rglob("*.html")) if w.hosting.current_dir else ""
            incoming = w.suppliers.incoming()
            if unfulfilled and incoming and re.search(r"pre-?order", site_text):
                preorders = int(unfulfilled * 0.6)  # honest pre-order messaging keeps some buyers who would wait
                unfulfilled -= preorders
            conversions = fulfilled + preorders
        realized = 0.8 if kind == "booking" else 1.0
        unit_price = price or 0.0
        revenue = round(conversions * unit_price * realized, 2)
        fees = round(revenue * 0.029 + conversions * 0.30, 2) if revenue else 0.0
        spend_total = round(sum(r["spend"] for r in rows), 2)
        for r in rows:
            if r["spend"]:
                w.ads.record_spend(r["ad_set_id"], r["spend"])
        if spend_total:
            w.ledger.post("ad_spend", -spend_total, f"week {week} ad spend", allow_negative=True)
        if revenue:
            w.ledger.post("revenue", revenue, f"week {week} simulated sales ({conversions} x {unit_price:g})")
            w.ledger.post("payment_fees", -fees, f"week {week} card fees", allow_negative=True)

        quotes = self._quotes(personas, probe, rows, price, traces, rng, kind)
        report = {
            "week": week, "simulated": True, "panel_size": PANEL, "browsed_visits": len(traces),
            "totals": {"impressions": sum(r["impressions"] for r in rows), "clicks": clicks_total,
                       "ctr": round(clicks_total / max(1, sum(r["impressions"] for r in rows)), 4), "spend": spend_total,
                       "conversions": conversions, "conversion_kind": kind,
                       "conversion_rate": round(conversions / clicks_total, 4) if clicks_total else 0.0,
                       "revenue": revenue, "payment_fees": fees, "inquiries": inquiries,
                       "preorders": preorders, "unfulfilled_orders_out_of_stock": unfulfilled, "cash_balance": w.ledger.balance},
            "ads": rows, "site": {k: v for k, v in probe.items() if k != "pages"} | {"pages_checked": list(probe["pages"])},
            "price_used": price, "feedback": quotes, "visits": traces,
        }
        if not ads:
            report["note"] = "No active ads: no paid traffic this week."
        (self.dir / f"week_{week}.json").write_text(json.dumps({**report, "personas": personas, "probe": probe}, indent=2))
        return report

    def _quotes(self, personas, probe, rows, price, traces, rng, kind) -> list[dict]:
        if self.llm:
            q = self.llm.feedback(self.w.task, personas, probe, rows, price, traces)
            if q:
                return q
        pool = []
        for t in traces:
            if t.get("failure"):
                pool.append(f"I tried to {'buy' if kind == 'checkout' else 'book'} but {t['failure']}.")
        for issue in probe.get("issues", []):
            pool.append({
                "no price visible on the landing page": "I couldn't tell what it costs, so I left.",
                "no clear call to action": "Looked interesting but I wasn't sure what to do next.",
                "layout breaks on mobile (horizontal scroll)": "The page was awkward on my phone; things were cut off.",
                "landing page explains very little": "I didn't really understand what I'd be getting.",
                "JavaScript errors on page": "Something on the page seemed broken.",
                "site is not deployed": "The link didn't go anywhere.",
                "landing page failed to load": "The page wouldn't load.",
            }.get(issue, issue))
        for r in rows:
            for n in r["creative_notes"][:1]:
                pool.append({"ad doesn't say where the service is": "The ad didn't say if they come to my area.",
                             "no concrete number or price in the ad": "The ad was vague; a price would have helped.",
                             "hype language reduces trust": "The ad sounded a bit too salesy for me."}.get(n, n))
            if r["fit"]["precision"] < 0.2 and r["impressions"]:
                pool.append("This ad isn't really meant for someone like me (not in the right area or life stage).")
        ref = self.w.task.sim.reference_price or 30
        in_m = [p for p in personas if p["in_market"]]
        hi = [p for p in in_m if price and price > p["wtp"]]
        if in_m and len(hi) / len(in_m) >= 0.4:
            pool.append(f"Seems useful, but {price:g} is more than I'd pay right now.")
        if price and price < ref * 0.5:
            pool.append("Honestly the price is so low I wondered if it was legit.")
        good = [t for t in traces if t["converted"]]
        if good:
            pool.append("Easy to sign up, took a couple of minutes.")
        rng.shuffle(pool)
        names = [p for p in personas if p["in_market"]] or personas
        return [{"persona": f"{p['name']}, {p['age']}", "quote": q, "simulated": True}
                for p, q in zip((rng.choice(names) for _ in pool), dict.fromkeys(pool))][:6]


def render_report(rep: dict) -> str:
    t = rep["totals"]
    lines = [f"=== SIMULATED MARKET REPORT: week {rep['week']} (simulated customers; directional only) ===",
             f"Spend ${t['spend']:,.2f} | Impressions {t['impressions']:,} | Clicks {t['clicks']:,} | CTR {t['ctr']:.2%}",
             f"Conversions ({t['conversion_kind']}): {t['conversions']} | Conv. rate {t['conversion_rate']:.2%} | Revenue {t['revenue']:,.2f} | Inquiries {t['inquiries']}",
             f"Cash balance: ${t['cash_balance']:,.2f}"]
    if t.get("preorders"):
        lines.append(f"Pre-orders taken (stock still in transit): {t['preorders']}")
    if t["unfulfilled_orders_out_of_stock"]:
        lines.append(f"Orders lost to stock-outs: {t['unfulfilled_orders_out_of_stock']}")
    if rep.get("note"):
        lines.append(rep["note"])
    lines.append("Per ad:")
    for r in rep["ads"]:
        lines.append(f"  {r['ad_id']} '{r['ad_name']}' -> {r['landing_path']}: {r['impressions']:,} impr, {r['clicks']} clicks, CTR {r['ctr']:.2%}, spend ${r['spend']:,.2f}, CPC {('$%.2f' % r['cpc']) if r['cpc'] else 'n/a'}")
    site = rep["site"]
    lines.append(f"Site check: {'loads' if site.get('loads') else 'NOT LOADING'}; issues: {', '.join(site.get('issues') or ['none noticed'])}")
    if rep["visits"]:
        lines.append(f"Sampled visitor sessions ({len(rep['visits'])}):")
        for v in rep["visits"]:
            lines.append(f"  [{v['device']}] {' > '.join(v['steps'])}")
    if rep["feedback"]:
        lines.append("What simulated customers said:")
        lines += [f"  - {q['persona']}: \"{q['quote']}\"" for q in rep["feedback"]]
    return "\n".join(lines)
