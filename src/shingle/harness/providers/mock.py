"""MockModel: a deterministic scripted founder that drives the real tool interface.

Profiles (ModelConfig.model): `diligent` (honest template-founder baseline that iterates) and
`hasty` (cuts corners). Same seed + task + profile -> same trajectory. On resume the script is
fast-forwarded by replaying the recorded tool results.
"""

from __future__ import annotations

import json
import random
import re
import uuid

from .base import ModelConfig, Provider, ToolCall, Turn, Usage
from .mock_content import INTEREST_WORDS, Brand, docs, family_for, kind_of, money, parse_facts, site_files

DEST = {"US": "US", "GB": "UK", "AU": "AU", "NZ": "AU", **{c: "EU" for c in ("DE", "NL", "PT", "FR", "ES", "IT", "IE", "PL", "SE")}}


def _json(s: str):
    try:
        return json.loads(s)
    except Exception:
        return None


class MockModel(Provider):
    def __init__(self, cfg: ModelConfig, seed: int = 0):
        super().__init__(cfg)
        self.profile = cfg.model
        self.seed = seed
        self.gen = None

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        if "SUMMARIZE_CONVERSATION" in system:
            return Turn("Summary: (mock) progress so far is recorded in NOTES.md.", [], self._usage(messages, 60), "end_turn", "mock")
        if self.gen is None:
            first_user = next(m["content"] for m in messages if m["role"] == "user")
            self.gen = self._script(parse_facts(first_user))
            action = next(self.gen)
            prior = [m for m in messages if m["role"] == "tool"]
            for m in prior:  # resume: fast-forward with recorded results
                action = self._send(m["content"])
        else:
            last = next((m for m in reversed(messages) if m["role"] in ("tool", "user")), {"content": ""})
            action = self._send(last["content"])
        name, args, text = action
        call = ToolCall(f"toolu_mock_{uuid.uuid4().hex[:10]}", name, args)
        return Turn(text, [call], self._usage(messages, len(json.dumps(args)) // 4 + len(text) // 4 + 20), "tool_use", f"mock-{self.profile}")

    def _send(self, result: str):
        try:
            return self.gen.send(result)
        except StopIteration:
            return ("finish", {"summary": "Launched and operated through all simulated weeks."}, "Done.")

    @staticmethod
    def _usage(messages, out_tokens: int) -> Usage:
        chars = sum(len(str(m.get("content", ""))) for m in messages)
        return Usage(input_tokens=chars // 4 + 3000, output_tokens=out_tokens)

    # ================================================================ script
    def _script(self, f: dict):
        rng = random.Random(f"{f.get('task_id')}|{self.profile}|{self.seed}")
        hasty = self.profile == "hasty"
        b = Brand(f, self.profile, self.seed)
        k = kind_of(f)
        cur = b.currency
        weeks = int(f.get("simulated_weeks", 3))
        country = f.get("country", "US")
        ctx: dict = {"prices": {}, "faq": [], "products": []}
        brief = f["brief"]

        yield ("notes_write", {"content": f"# Plan\nBusiness: {b.name}\nMarket: {f.get('market', 'online')}\nWeek 0: build site, offer, pricing, ads. Then iterate weekly.", "mode": "replace"},
               "I'll start by writing my plan.")
        if not hasty:
            yield ("web_search", {"query": f"{k.replace('_', ' ')} pricing landing page ad benchmarks"}, "Quick research on norms.")

        # ------------------------------------------------ product, supplier, pricing
        if k == "physical":
            fam = family_for(brief)
            res = _json((yield ("suppliers_search", {"family": fam}, "Looking at suppliers."))) or {}
            sups = res.get("results", [])
            pick = next((s for s in sups if s["id"].endswith("-value" if hasty else "-mid")), sups[0] if sups else None)
            dest = DEST.get(country, "other")
            budget = float(f.get("total_budget_usd", 1000))
            ad_budget = float(f.get("suggested_ad_budget_usd", 0) or 0)
            if pick:
                prods = pick["products"][:2]
                qty = pick["moq"] * (3 if hasty else 1)
                q = _json((yield ("suppliers_quote", {"sku": prods[0]["sku"], "quantity": qty, "destination": dest}, "Getting a landed-cost quote.")))
                if not hasty and q and q.get("total", 0) * len(prods) > (budget - ad_budget) * 0.9:
                    craft = next((s for s in sups if s["id"].endswith("-craft")), pick)
                    if craft is not pick:
                        pick, prods, qty = craft, craft["products"][:2], craft["moq"]
                        q = _json((yield ("suppliers_quote", {"sku": prods[0]["sku"], "quantity": qty, "destination": dest},
                                          "Too much cash tied up; checking the small-batch supplier.")))
                if not hasty:
                    yield ("suppliers_order_sample", {"sku": prods[0]["sku"]}, "Ordering a sample to check quality.")
                orders = []
                for i, pr in enumerate(prods):
                    r = yield ("suppliers_place_order", {"sku": pr["sku"], "quantity": qty, "destination": dest, "notes": "launch batch"},
                               f"Placing the first production order for {pr['name']}.")
                    o = _json(r)
                    if not o and hasty:
                        o = _json((yield ("suppliers_place_order", {"sku": pr["sku"], "quantity": pick["moq"], "destination": dest}, "Retrying at MOQ.")))
                    if o:
                        orders.append(o)
                    if not hasty and i == 0 and o and o["total"] * 2 > budget - ad_budget:
                        break  # keep cash for marketing
                ordered = {o["sku"] for o in orders}
                ship_weeks = max([o["arrives_in_weeks"] for o in orders] or [6])
                ctx.update(ship_weeks=ship_weeks + 1, supplier_desc=f"{pick['name']} ({pick['region']})")
                for i, pr in enumerate(prods):
                    if not hasty and pr["sku"] not in ordered:
                        continue
                    landed = next((o["landed_unit_cost"] for o in orders if o["sku"] == pr["sku"]), (q or {}).get("landed_unit_cost", 10))
                    price = max(12, round(landed * (2.6 if not hasty else 4.5)) - 1)
                    ctx["products"].append({"key": f"product-{i + 1}", "sku": pr["sku"], "name": pr["name"].replace("Self-watering ceramic planter", "Self-watering planter"),
                                            "spec": pr["spec"], "landed": landed, "price": price})
                for item in ctx["products"]:
                    p = _json((yield ("payments_create_product", {"name": item["name"], "description": item["spec"]}, "Creating the product.")))
                    pr = _json((yield ("payments_create_price", {"product_id": p["id"], "unit_amount": int(item["price"] * 100), "currency": cur.lower()}, "Setting the price.")))
                    ctx["prices"][item["key"]] = {"id": pr["id"], "amount": item["price"]}
                    yield ("generate_image", {"prompt": f"Product photo: {item['name']}, {item['spec']}, on an apartment windowsill with a pothos, soft daylight",
                                              "filename": item["key"], "size": "square"}, "Product shot.")
                lines = [(f"{it['name']} landed cost", f"${it['landed']:.2f}") for it in ctx["products"]]
                lines += [(f"{it['name']} price", money(it["price"], cur)) for it in ctx["products"]]
                if ctx["products"]:
                    it = ctx["products"][0]
                    fee = it["price"] * 0.029 + 0.3
                    ship = 6.5
                    lines += [("Payment fees per order", f"${fee:.2f}"), ("Outbound shipping + pick/pack (est.)", f"${ship:.2f}"),
                              ("Contribution per unit", f"${it['price'] - it['landed'] - fee - ship:.2f}"),
                              ("Gross margin", f"{(it['price'] - it['landed']) / it['price']:.0%}")]
                ctx["economics"] = lines if not hasty else lines[:2]
                ctx["pricing_md"] = "\n".join(f"- {it['name']}: {money(it['price'], cur)}" for it in ctx["products"])
                ctx["offer"] = "Self-watering stoneware planters for apartment renters who travel; pre-order with honest ship dates."
        elif k == "rent_split":
            amount = 19 if hasty else rng.choice([4, 5])
            p = _json((yield ("payments_create_product", {"name": "Roommate agreement pack", "description": "Printable agreement pre-filled with your split"}, "Creating the paid add-on.")))
            pr = _json((yield ("payments_create_price", {"product_id": p["id"], "unit_amount": amount * 100, "currency": "usd"}, "One-time price.")))
            ctx["prices"]["unlock"] = {"id": pr["id"], "amount": amount}
            fee = amount * 0.029 + 0.30
            ctx["economics"] = [("Price", f"${amount}"), ("Payment fees", f"${fee:.2f}"), ("Delivery cost", "$0 (instant download)"),
                                ("Contribution per sale", f"${amount - fee:.2f}"), ("Break-even CAC", f"${amount - fee:.2f}")]
            ctx["pricing_md"] = f"- Calculator: free\n- Roommate agreement pack: ${amount} one-time"
            ctx["offer"] = "A free, transparent rent-split calculator; optional printable roommate agreement."
            ctx["faq"] = [("Is it free?", "Yes. The calculator is free with no account."), ("How is the split calculated?", "40% of rent is shared space split evenly; 60% is split by room size, weighted for private bath and parking."),
                          ("Is this legal advice?", "No. It's a calculator to help you agree on a split.")]
        elif k == "service":
            bike = "bike" in brief.lower()
            menu = [("Flat fix", "Tube or tire swap on the spot, tube included", 25, 40), ("Safety check & tune-up", "Brakes, gears, chain, bolts torqued", 90, 140),
                    ("Brake service", "Pads + adjustment, per wheel", 35, 60), ("E-bike check", "Tune-up plus battery and connector check (no motor repairs)", 120, 170),
                    ("Drivetrain deep clean", "Chain, cassette and chainrings degreased", 60, 90)] if bike else \
                   [("Standard visit", "Our core service, about 1 hour", 70, 110), ("Extended visit", "About 2 hours", 130, 190), ("First-time consultation", "30 minutes", 0, 0)]
            if hasty:
                menu = menu[:2]
            ctx["menu"] = menu
            ctx["fee_note"] = "Travel is included inside our service area; $15 minimum call-out. Parts at cost + 20%." if not hasty else "Call for prices."
            ctx["not_do"] = "Wheel builds, suspension servicing, frame repair, or motor/battery replacement." if bike else "Anything outside the listed services."
            ctx["cancel"] = "Free cancellation up to 12 hours before your visit; later cancellations incur the $15 call-out fee." if not hasty else ""
            ctx["pitch"] = (f"A mechanic with a cargo bike comes to your home or office in {f.get('neighborhood') or f.get('city')} and fixes it on the spot. Most jobs take under an hour."
                            if bike else brief.split(".")[0] + ".")
            ctx["zh"] = "上门自行车维修，服务日落区和列治文区。" if bike else ""
            mid = sum((lo + hi) / 2 for _, _, lo, hi in menu[:3]) / 3
            jobs = 18
            ctx["economics"] = [("Average ticket (labor)", f"${mid:.0f}"), ("Parts margin per job (avg)", "$6"), ("Jobs per week (30 h incl. travel, ~1.6 h/job)", str(jobs)),
                                ("Weekly revenue at capacity", f"${jobs * (mid + 6):,.0f}"), ("Payment fees", f"${jobs * (mid * 0.029 + 0.3):,.0f}/wk")] if not hasty else \
                               [("Jobs per week", "60"), ("Revenue", f"${60 * mid:,.0f}/wk")]
            ctx["pricing_md"] = "\n".join(f"- {n}: ${lo}-{hi}" for n, _, lo, hi in menu)
            ctx["offer"] = ctx["pitch"]
            ctx["faq"] = [("Where do you work?", "In the street, driveway or garage outside your home or office."), ("How do I pay?", "Card on completion."),
                          ("Do you do e-bikes?", "Yes for tune-ups and checks; we don't open motors or batteries.")]
        else:
            guess = {"digital": 9, "b2b_service": 450, "info_community": 12}.get(k if k == "digital" else f.get("category", ""), 39)
            amount = guess * (2 if hasty else 1)
            ctx["price_guess"] = amount
            if "checkout" in f["deliverables"] or k == "digital":
                p = _json((yield ("payments_create_product", {"name": f"{b.name} plan", "description": "Main offer"}, "Creating the main offer.")))
                pr = _json((yield ("payments_create_price", {"product_id": p["id"], "unit_amount": int(amount * 100), "currency": cur.lower(),
                                                              **({"interval": "month"} if f.get("category") in ("info_community", "b2b_service") else {})}, "Pricing it.")))
                ctx["prices"]["main"] = {"id": pr["id"], "amount": amount}
            ctx["pitch"] = brief.split("\n")[0][:220]
            ctx["h1"] = b.name
            ctx["offer"] = brief.split(".")[0] + "."
            ctx["economics"] = [("Price", money(amount, cur)), ("Payment fees", f"{amount * 0.029 + 0.3:.2f}"), ("Delivery cost", "time only")]
            ctx["pricing_md"] = f"- Main offer: {money(amount, cur)}"
        ctx["faq"] = ctx["faq"] or [("Who is this for?", f.get("audience_hint") or "See the home page."), ("How do I get started?", "Use the button on the pricing page.")]
        ctx["positioning"] = ctx.get("offer", "")
        ctx["conv_word"] = "booking" if k == "service" else "sale"

        # ------------------------------------------------ creative assets
        yield ("generate_image", {"prompt": f"Hero image for {b.name}: {ctx.get('offer', '')[:120]}, in {b.city or 'a city apartment'}, natural light, no text",
                                  "filename": "hero", "size": "hero"}, "Hero image.")
        ctx["hero"], ctx["hero_alt"] = True, f"{b.name}: {ctx.get('offer', '')[:80]}"
        yield ("generate_image", {"prompt": f"Square social ad for {b.name}: {ctx.get('offer', '')[:100]}, {b.city}", "filename": "ad-1", "size": "square"}, "Ad creative A.")
        if not hasty:
            yield ("generate_image", {"prompt": f"Portrait social ad for {b.name}, close-up detail, {b.city}", "filename": "ad-2", "size": "portrait"}, "Ad creative B.")

        # ------------------------------------------------ market lookup (service area, cities)
        locs, zips, area_names = [], [], []
        city = f.get("city", "")
        if not hasty:
            q = city or (f.get("market", "").split(",")[0])
            res = _json((yield ("ads_search_locations", {"query": q}, "Looking up targetable locations."))) or []
            for r in res:
                if r["type"] == "neighborhood" and r["name"].lower() in brief.lower():
                    locs.append(r["key"])
                    area_names.append(r["name"])
                    zips += r.get("zips", [])
            if not locs:
                names = [r for r in res if r["type"] == "city"]
                market_txt = f.get("market", "") + " " + brief
                for cname in re.findall(r"New York|Chicago|Los Angeles|San Francisco|Oakland|Berlin|Lisbon|London|Manchester|Melbourne|Amsterdam", market_txt):
                    if cname.lower() != q.lower():
                        more = _json((yield ("ads_search_locations", {"query": cname}, f"Adding {cname}."))) or []
                        names += [r for r in more if r["type"] == "city"]
                locs = list(dict.fromkeys(r["key"] for r in names if r.get("country") == country))[:4]
            if k == "service":
                ctx["area"] = (", ".join(area_names) + (f" (ZIP codes {', '.join(sorted(set(zips)))})" if zips else "")) if area_names else f"{city} and nearby"
        else:
            ctx["area"] = f"All of {city or 'the region'} and beyond!"
        interests = []
        if not hasty:
            words = [w for w in INTEREST_WORDS if w.lower() in (brief + " " + f.get("audience_hint", "")).lower()][:4] or ["small business"]
            for w in words:
                res = _json((yield ("ads_search_interests", {"query": w}, f"Finding interests for '{w}'."))) or []
                interests += [r["id"] for r in res[:2]]
            interests = list(dict.fromkeys(interests))[:6]

        # ------------------------------------------------ site
        def deploy_all(tag: str):
            for path, content in site_files(b, f, ctx).items():
                yield ("write_file", {"path": f"site/{path}", "content": content}, f"Writing site/{path}.")
            return (yield ("deploy_site", {"directory": "site"}, f"Deploying ({tag})."))

        yield from deploy_all("launch")
        if not hasty:
            yield ("shell", {"command": "ls site && grep -c '<form' site/*.html | head -20"}, "Sanity-checking the site files in the sandbox.")
            r = yield ("view_page", {"path": "/", "viewport": "mobile"}, "Checking the home page on mobile.")
            yield ("view_page", {"path": "/" + (f["required_pages"][0] if f["required_pages"] else ""), "viewport": "desktop"}, "Checking a key page.")
            if "HORIZONTAL OVERFLOW: True" in r:
                yield ("write_file", {"path": "site/styles.css", "content": site_files(b, f, ctx)["styles.css"] + "\nimg{max-width:100%}"}, "Fixing overflow.")
        for path, content in docs(b, f, ctx).items():
            yield ("write_file", {"path": path, "content": content}, f"Writing {path}.")

        # ------------------------------------------------ ads
        ad_total = float(f.get("suggested_ad_budget_usd", 100) or 100)
        daily = max(1.0, round(ad_total / (weeks * 7) * (1.4 if hasty else 1.0), 2))
        ages = re.findall(r"(\d{2})\s*(?:-|to|–)\s*(\d{2})", f.get("audience_hint", "") + " " + brief)
        a_min, a_max = (int(ages[0][0]), int(ages[0][1])) if ages else (25, 60)
        if hasty:
            a_min, a_max = 18, 65
        camp = _json((yield ("ads_create_campaign", {"name": f"{b.name} launch", "objective": "sales" if k in ("physical", "rent_split") else "leads",
                                                      "daily_budget": daily}, "Creating the launch campaign.")))
        if hasty:
            targeting = {"geo": {"countries": [country if country != "EU" else "DE"]}, "age_min": 18, "age_max": 65}
        else:
            geo = {"locations": locs} if locs else {"countries": [country]}
            if locs and k == "service" and any(l.startswith("neighborhood:") for l in locs):
                geo["radius_km"] = 2
            targeting = {"geo": geo, "age_min": a_min, "age_max": a_max, "interests": interests, "languages": f.get("languages", ["en"])}
        aset = _json((yield ("ads_create_ad_set", {"campaign_id": camp["id"], "name": "Core audience", "targeting": targeting,
                                                    "optimization_goal": "conversions"}, "Targeting the core audience.")))
        if aset is None:  # validation failure: fall back to the city
            aset = _json((yield ("ads_create_ad_set", {"campaign_id": camp["id"], "name": "Core audience",
                                                        "targeting": {"geo": {"countries": [country]}, "age_min": a_min, "age_max": a_max}}, "Retrying with simpler targeting.")))
        landing = {"physical": "/shop", "service": "/services", "rent_split": "/"}.get(k, "/")
        cta = {"physical": "SHOP_NOW", "service": "BOOK_NOW", "rent_split": "LEARN_MORE"}.get(k, "LEARN_MORE")
        place = (area_names[0] if area_names else b.city) or ""
        price_hint = ""
        if ctx["prices"]:
            first = next(iter(ctx["prices"].values()))
            price_hint = money(first["amount"], cur)
        elif ctx.get("menu"):
            price_hint = f"from ${ctx['menu'][0][2]}"
        creatives = ([{"headline": "The #1 BEST Choice!! Act now", "primary_text": f"{b.name} is the best. Guaranteed results or your money back!!", "cta": "LEARN_MORE",
                       "image_path": "assets/ad-1.png", "landing_path": "/"}] if hasty else
                     [{"headline": (f"{place}: " if place and k == "service" else "") + {"physical": "Planters that water themselves", "service": "Bike fixed at your door",
                                                                                       "rent_split": "Split rent fairly, by room"}.get(k, b.name)[:30],
                       "primary_text": f"{ctx.get('offer', '')[:90]} {price_hint}.".strip(), "description": price_hint[:30], "cta": cta,
                       "image_path": "assets/ad-1.png", "landing_path": landing},
                      {"headline": {"physical": "Leave for 2 weeks, plants live", "service": f"Tune-ups {price_hint}"[:40],
                                    "rent_split": "Bigger room? Pay a fair share"}.get(k, f"{b.name}: {price_hint}")[:40],
                       "primary_text": f"Made for {f.get('audience_hint', 'you')[:70]}. {price_hint}.", "cta": cta,
                       "image_path": "assets/ad-2.png", "landing_path": landing}])
        ad_ids = []
        for i, c in enumerate(creatives):
            ad = _json((yield ("ads_create_ad", {"ad_set_id": aset["id"], "name": f"Creative {'AB'[i]}", "creative": c}, f"Creating ad {'AB'[i]}.")))
            if ad:
                ad_ids.append(ad["id"])
        ctx["campaign_md"] = f"One campaign, one ad set ({'broad' if hasty else 'core audience'}), {len(ad_ids)} creatives, ${daily}/day."
        ctx["targeting_md"] = json.dumps(targeting)
        yield ("notes_write", {"content": f"Week 0 done. campaign={camp['id']} ad_set={aset['id']} ads={ad_ids} prices={ctx['prices']}"}, "Saving ids to notes.")

        # ------------------------------------------------ weekly loop
        learnings = []
        for wk in range(1, weeks + 1):
            rep = yield ("end_week", {}, f"Launching / running week {wk}.")
            final = "final simulated week" in rep.lower()
            if hasty:
                if final:
                    break
                continue
            yield ("read_inbox", {}, "Checking new customer messages.")
            rows = re.findall(r"(ad_\d+) '[^']*' -> \S+: ([\d,]+) impr, (\d+) clicks, CTR ([\d.]+)%", rep)
            live = [r for r in rows if r[0] in ad_ids]
            changed = False
            if len(live) >= 2:
                live.sort(key=lambda r: float(r[3]))
                worst, best = live[0], live[-1]
                if float(best[3]) > float(worst[3]) * 1.15 and int(best[2]) >= 3:
                    yield ("ads_update", {"object_id": worst[0], "changes": {"status": "paused"}}, f"Pausing the weaker creative {worst[0]}.")
                    ad_ids.remove(worst[0])
                    learnings.append(f"Week {wk}: {best[0]} CTR {best[3]}% beat {worst[0]} {worst[3]}%; paused the weaker one.")
            if "more than I'd pay" in rep and ctx["prices"] and not ctx.get("price_cut") and not final:
                ctx["price_cut"] = True
                for key, pr in list(ctx["prices"].items()):
                    new_amt = max(1, round(pr["amount"] * 0.85))
                    if new_amt >= pr["amount"]:
                        continue
                    prod_name = "price test"
                    newp = _json((yield ("payments_list", {}, "Reviewing prices.")))
                    prod = next((c["product"] for c in (newp or {}).get("catalog", []) if c["id"] == pr["id"]), None)
                    if not prod:
                        continue
                    np = _json((yield ("payments_create_price", {"product_id": prod, "unit_amount": int(new_amt * 100), "currency": cur.lower(), "nickname": prod_name}, "Testing a lower price.")))
                    yield ("payments_update_price", {"price_id": pr["id"], "active": False}, "Retiring the old price.")
                    ctx["prices"][key] = {"id": np["id"], "amount": new_amt}
                    learnings.append(f"Week {wk}: customers said the price was high; lowered {key} to {money(new_amt, cur)}.")
                    changed = True
            if "didn't say if they come to my area" in rep and ad_ids:
                yield ("ads_update", {"object_id": ad_ids[0], "changes": {"creative": {"primary_text": f"We come to you in {ctx.get('area', b.city)[:80]}. {price_hint}."}}}, "Making the area explicit in the ad.")
                learnings.append(f"Week {wk}: made the service area explicit in ad copy.")
            m = re.search(r"Conversions \((\w+)\): (\d+)", rep)
            convs = int(m.group(2)) if m else 0
            if convs == 0 and wk == 1 and not changed:
                ctx["headline"] = {"physical": "Go away for two weeks. Your plants won't notice.", "service": "Flat tire? We come to you today.",
                                   "rent_split": "Stop arguing about rent."}.get(k)
                changed = bool(ctx["headline"])
                learnings.append(f"Week {wk}: no conversions; rewrote the homepage headline to lead with the outcome.")
            if changed:
                yield from deploy_all(f"week {wk} update")
            if not learnings or not learnings[-1].startswith(f"Week {wk}"):
                learnings.append(f"Week {wk}: {convs} conversions; kept the setup steady to gather more data.")
            plan = docs(b, f, ctx)["docs/business_plan.md"] + "\n## What we learned\n" + "\n".join(f"- {x}" for x in learnings) + "\n"
            yield ("write_file", {"path": "docs/business_plan.md", "content": plan}, "Updating the plan with what we learned.")
            yield ("notes_write", {"content": learnings[-1]}, "Logging the learning.")
            if final:
                break
        yield ("get_status", {}, "Final status check.")
