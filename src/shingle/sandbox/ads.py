"""Simulated ad platform. Validates like a real one; spends only simulated money.

Objects: campaign -> ad set (targeting + budget) -> ad (creative). Limits follow common
social-ad platform conventions (headline 40, primary text 125 recommended / 500 max,
description 30, standard aspect ratios, min 600px, special ad categories restrict targeting).
"""

from __future__ import annotations

import json
import math
import re
import time
from functools import lru_cache
from pathlib import Path

import yaml
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..config import ROOT

OBJECTIVES = ("awareness", "traffic", "leads", "sales")
OPT_GOALS = ("impressions", "link_clicks", "leads", "conversions")
CTAS = ("LEARN_MORE", "SHOP_NOW", "BOOK_NOW", "SIGN_UP", "CONTACT_US", "GET_QUOTE", "SUBSCRIBE", "DOWNLOAD", "ORDER_NOW", "APPLY_NOW")
SPECIAL = ("none", "housing", "employment", "credit")
RATIOS = {"1:1": 1.0, "4:5": 0.8, "1.91:1": 1.91, "9:16": 9 / 16}
ZIP_PATTERNS = {"US": r"^\d{5}$", "GB": r"^[A-Z]{1,2}\d[A-Z\d]?$", "DE": r"^\d{5}$", "PT": r"^\d{4}(-\d{3})?$", "MX": r"^\d{5}$",
                "IN": r"^\d{6}$", "AU": r"^\d{4}$", "KE": r"^\d{5}$", "NG": r"^\d{6}$", "CA": r"^[A-Z]\d[A-Z]$"}


class AdsError(Exception):
    pass


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


@lru_cache
def interests() -> dict[str, dict]:
    raw = yaml.safe_load((ROOT / "data" / "ad_interests.yaml").read_text())
    return {slug(n): {"id": slug(n), "name": n, "category": cat} for cat, names in raw.items() for n in names}


@lru_cache
def gazetteer() -> dict[str, dict]:
    raw = yaml.safe_load((ROOT / "data" / "geo.yaml").read_text())
    g: dict[str, dict] = {}
    for c in raw["countries"]:
        g[f"country:{c}"] = {"key": f"country:{c}", "type": "country", "name": c, "country": c}
    for r in raw["regions"]:
        g[r["key"]] = {**r, "type": "region"}
    for c in raw["cities"]:
        k = f"city:{c['country']}:{slug(c['name'])}"
        g[k] = {**c, "key": k, "type": "city"}
    for n in raw["neighborhoods"]:
        k = f"neighborhood:{n['country']}:{slug(n['city'])}:{slug(n['name'])}"
        g[k] = {**n, "key": k, "type": "neighborhood"}
    try:  # task markets are always targetable
        from ..tasks import load_tasks

        for t in load_tasks().values():
            m = t.market
            if m and m.city:
                k = f"city:{m.country}:{slug(m.city)}"
                g.setdefault(k, {"key": k, "type": "city", "name": m.city, "country": m.country, "lat": m.lat, "lon": m.lon})
                if m.neighborhood:
                    k = f"neighborhood:{m.country}:{slug(m.city)}:{slug(m.neighborhood)}"
                    g.setdefault(k, {"key": k, "type": "neighborhood", "name": m.neighborhood, "city": m.city,
                                     "country": m.country, "lat": m.lat, "lon": m.lon})
    except Exception:
        pass
    return g


class Geo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    countries: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list, description="keys from ads_search_locations")
    zips: list[str] = Field(default_factory=list, description="'<CC>:<postcode>', e.g. 'US:94122'")
    radius_km: float | None = None


class Targeting(BaseModel):
    model_config = ConfigDict(extra="forbid")
    geo: Geo
    age_min: int = 18
    age_max: int = 65
    genders: list[str] = Field(default_factory=lambda: ["all"])
    languages: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    exclude_interests: list[str] = Field(default_factory=list)
    devices: list[str] = Field(default_factory=lambda: ["mobile", "desktop"])


class Creative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str
    primary_text: str
    description: str = ""
    cta: str
    image_path: str
    landing_path: str = "/"


def _validate_targeting(t: Targeting, special: str) -> list[str]:
    errs, warns = [], []
    gz = gazetteer()
    g = t.geo
    if not (g.countries or g.locations or g.zips):
        errs.append("targeting.geo needs at least one of countries, locations or zips")
    for c in g.countries:
        if f"country:{c}" not in gz:
            errs.append(f"unknown country code '{c}'")
    for k in g.locations:
        if k not in gz:
            errs.append(f"unknown location key '{k}' (use ads_search_locations)")
    for z in g.zips:
        cc, _, code = z.partition(":")
        pat = ZIP_PATTERNS.get(cc)
        if not code or (pat and not re.match(pat, code.upper())):
            errs.append(f"invalid postcode '{z}' (format '<CC>:<code>', e.g. 'US:94122')")
    if g.radius_km is not None:
        if not 1 <= g.radius_km <= 80:
            errs.append("radius_km must be between 1 and 80")
        if not any(gz.get(k, {}).get("type") in ("city", "neighborhood") for k in g.locations):
            errs.append("radius_km only applies to city or neighborhood locations")
    if not 13 <= t.age_min <= t.age_max <= 65:
        errs.append("ages must satisfy 13 <= age_min <= age_max <= 65")
    if any(x not in ("all", "female", "male") for x in t.genders):
        errs.append("genders must be from: all, female, male")
    known = interests()
    for i in t.interests + t.exclude_interests:
        if i not in known:
            errs.append(f"unknown interest '{i}' (use ads_search_interests)")
    if any(d not in ("mobile", "desktop") for d in t.devices) or not t.devices:
        errs.append("devices must be a non-empty subset of mobile, desktop")
    if special != "none":
        if (t.age_min, t.age_max) != (18, 65) or t.genders != ["all"]:
            errs.append(f"special ad category '{special}': age must be 18-65 and genders 'all'")
        if g.zips:
            errs.append(f"special ad category '{special}': postcode targeting is not allowed")
        if g.radius_km is not None and g.radius_km < 24:
            errs.append(f"special ad category '{special}': minimum radius is 24 km")
    if errs:
        raise AdsError("; ".join(errs))
    if not t.interests:
        warns.append("no interests set: delivery will be broad")
    if t.age_max - t.age_min >= 47:
        warns.append("very broad age range")
    return warns


def image_spec(path: Path) -> dict:
    if not path.is_file():
        raise AdsError(f"image not found: {path.name}")
    if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        raise AdsError("image must be PNG, JPG or WEBP")
    if path.stat().st_size > 30_000_000:
        raise AdsError("image larger than 30 MB")
    with Image.open(path) as im:
        w, h = im.size
    if w < 600 or h < 600 * 0.5:
        raise AdsError(f"image too small ({w}x{h}); minimum width is 600px")
    ratio = w / h
    match = next((k for k, v in RATIOS.items() if abs(ratio - v) / v <= 0.03), None)
    if not match:
        raise AdsError(f"aspect ratio {w}x{h} not supported; use 1:1, 4:5, 1.91:1 or 9:16")
    return {"width": w, "height": h, "ratio": match}


class AdPlatform:
    def __init__(self, state_path: Path, workspace_root: Path, clock):
        self.state_path = state_path
        self.ws = workspace_root
        self.clock = clock  # callable -> current simulated week
        self.state = {"campaigns": {}, "ad_sets": {}, "ads": {}, "history": [], "seq": 0}
        if state_path.exists():
            self.state = json.loads(state_path.read_text())

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2))

    def _new_id(self, prefix: str) -> str:
        self.state["seq"] += 1
        return f"{prefix}_{self.state['seq']:04d}"

    def _log(self, action: str, obj_id: str, data: dict) -> None:
        self.state["history"].append({"week": self.clock(), "action": action, "id": obj_id, "data": data, "ts": time.time()})

    # ----------------------------------------------------------------- lookup
    @staticmethod
    def search_interests(query: str, limit: int = 15) -> list[dict]:
        q = query.lower().strip()
        hits = [v for v in interests().values() if q in v["name"].lower() or q in v["category"].lower()]
        return hits[:limit]

    @staticmethod
    def search_locations(query: str, limit: int = 15) -> list[dict]:
        q = query.lower().strip()
        out = []
        for v in gazetteer().values():
            hay = f"{v.get('name', '')} {v.get('city', '')} {v.get('country', '')} {' '.join(v.get('zips', []))}".lower()
            if q and q in hay:
                out.append({k: v[k] for k in ("key", "type", "name", "country") if k in v} | ({"zips": v["zips"]} if v.get("zips") else {}))
        return out[:limit]

    # ----------------------------------------------------------------- create
    def create_campaign(self, name: str, objective: str, daily_budget: float | None = None,
                        lifetime_budget: float | None = None, special_ad_category: str = "none") -> dict:
        errs = []
        if not name.strip():
            errs.append("name is required")
        if objective not in OBJECTIVES:
            errs.append(f"objective must be one of {', '.join(OBJECTIVES)}")
        if special_ad_category not in SPECIAL:
            errs.append(f"special_ad_category must be one of {', '.join(SPECIAL)}")
        if daily_budget is not None and lifetime_budget is not None:
            errs.append("set daily_budget or lifetime_budget, not both (or neither to budget at ad-set level)")
        for b in (daily_budget, lifetime_budget):
            if b is not None and b < 1:
                errs.append("budgets must be at least $1")
        if errs:
            raise AdsError("; ".join(errs))
        cid = self._new_id("cmp")
        c = {"id": cid, "name": name[:100], "objective": objective, "daily_budget": daily_budget,
             "lifetime_budget": lifetime_budget, "special_ad_category": special_ad_category, "status": "active",
             "created_week": self.clock()}
        self.state["campaigns"][cid] = c
        self._log("create_campaign", cid, c)
        self._save()
        return c

    def create_ad_set(self, campaign_id: str, name: str, targeting: dict, daily_budget: float | None = None,
                      optimization_goal: str = "link_clicks") -> dict:
        camp = self.state["campaigns"].get(campaign_id)
        if not camp:
            raise AdsError(f"no such campaign {campaign_id}")
        try:
            t = Targeting.model_validate(targeting)
        except ValidationError as e:
            raise AdsError(f"invalid targeting: {e.errors()[0]['loc']} {e.errors()[0]['msg']}") from None
        warns = _validate_targeting(t, camp["special_ad_category"])
        if optimization_goal not in OPT_GOALS:
            raise AdsError(f"optimization_goal must be one of {', '.join(OPT_GOALS)}")
        camp_budget = camp["daily_budget"] or camp["lifetime_budget"]
        if camp_budget is None and daily_budget is None:
            raise AdsError("ad set needs daily_budget because the campaign has no campaign-level budget")
        if camp_budget is not None and daily_budget is not None:
            raise AdsError("campaign uses campaign budget; do not set ad-set daily_budget")
        if daily_budget is not None and daily_budget < 1:
            raise AdsError("daily_budget must be at least $1")
        sid = self._new_id("set")
        s = {"id": sid, "campaign_id": campaign_id, "name": name[:100], "targeting": t.model_dump(),
             "daily_budget": daily_budget, "optimization_goal": optimization_goal, "status": "active",
             "created_week": self.clock()}
        self.state["ad_sets"][sid] = s
        self._log("create_ad_set", sid, s)
        self._save()
        return {**s, "warnings": warns}

    def _validate_creative(self, c: Creative) -> tuple[dict, list[str]]:
        errs, warns = [], []
        if not c.headline.strip():
            errs.append("headline is required")
        if len(c.headline) > 40:
            errs.append(f"headline is {len(c.headline)} chars (max 40)")
        if not c.primary_text.strip():
            errs.append("primary_text is required")
        if len(c.primary_text) > 500:
            errs.append(f"primary_text is {len(c.primary_text)} chars (max 500)")
        elif len(c.primary_text) > 125:
            warns.append("primary_text over 125 chars will be truncated in most placements")
        if len(c.description) > 30:
            errs.append(f"description is {len(c.description)} chars (max 30)")
        if c.cta not in CTAS:
            errs.append(f"cta must be one of {', '.join(CTAS)}")
        if not c.landing_path.startswith("/"):
            errs.append("landing_path must be a path on your deployed site, starting with '/'")
        if sum(ch.isupper() for ch in c.headline) > 0.7 * max(1, sum(ch.isalpha() for ch in c.headline)) and len(c.headline) > 8:
            errs.append("headline in all caps is not allowed")
        spec = {}
        try:
            img = (self.ws / c.image_path.lstrip("/")).resolve()
            if self.ws.resolve() not in img.parents:
                raise AdsError("image_path must be inside the workspace")
            spec = image_spec(img)
        except AdsError as e:
            errs.append(str(e))
        if errs:
            raise AdsError("; ".join(errs))
        return spec, warns

    def create_ad(self, ad_set_id: str, name: str, creative: dict) -> dict:
        if ad_set_id not in self.state["ad_sets"]:
            raise AdsError(f"no such ad set {ad_set_id}")
        try:
            c = Creative.model_validate(creative)
        except ValidationError as e:
            raise AdsError(f"invalid creative: {e.errors()[0]['loc']} {e.errors()[0]['msg']}") from None
        spec, warns = self._validate_creative(c)
        aid = self._new_id("ad")
        a = {"id": aid, "ad_set_id": ad_set_id, "name": name[:100], "creative": c.model_dump(), "image": spec,
             "status": "active", "created_week": self.clock()}
        self.state["ads"][aid] = a
        self._log("create_ad", aid, a)
        self._save()
        return {**a, "warnings": warns}

    # ----------------------------------------------------------------- update
    def update(self, object_id: str, changes: dict) -> dict:
        for kind in ("campaigns", "ad_sets", "ads"):
            if object_id in self.state[kind]:
                obj = self.state[kind][object_id]
                break
        else:
            raise AdsError(f"no such object {object_id}")
        allowed = {"campaigns": {"name", "daily_budget", "lifetime_budget", "status"},
                   "ad_sets": {"name", "daily_budget", "targeting", "status", "optimization_goal"},
                   "ads": {"name", "creative", "status"}}[kind]
        bad = set(changes) - allowed
        if bad:
            raise AdsError(f"cannot change {sorted(bad)} on {kind[:-1]}; allowed: {sorted(allowed)}")
        if "status" in changes and changes["status"] not in ("active", "paused"):
            raise AdsError("status must be active or paused")
        new = {**obj, **changes}
        warns: list[str] = []
        if kind == "ad_sets" and "targeting" in changes:
            camp = self.state["campaigns"][obj["campaign_id"]]
            t = Targeting.model_validate(changes["targeting"])
            warns = _validate_targeting(t, camp["special_ad_category"])
            new["targeting"] = t.model_dump()
        if kind == "ads" and "creative" in changes:
            c = Creative.model_validate({**obj["creative"], **changes["creative"]})
            new["image"], warns = self._validate_creative(c)
            new["creative"] = c.model_dump()
        for b in ("daily_budget", "lifetime_budget"):
            if b in changes and changes[b] is not None and changes[b] < 1:
                raise AdsError("budgets must be at least $1")
        self.state[kind][object_id] = new
        self._log("update", object_id, changes)
        self._save()
        return {**new, "warnings": warns}

    # ----------------------------------------------------------------- reads
    def overview(self) -> dict:
        return {k: list(self.state[k].values()) for k in ("campaigns", "ad_sets", "ads")}

    def active_ads(self) -> list[tuple[dict, dict, dict]]:
        out = []
        for a in self.state["ads"].values():
            s = self.state["ad_sets"][a["ad_set_id"]]
            c = self.state["campaigns"][s["campaign_id"]]
            if a["status"] == c["status"] == s["status"] == "active":
                out.append((c, s, a))
        return out

    def weekly_budgets(self) -> dict[str, float]:
        """Planned 7-day spend per ad set (campaign budgets split evenly across its active ad sets)."""
        out: dict[str, float] = {}
        live_sets = {s["id"] for _, s, _ in self.active_ads()}
        for c in self.state["campaigns"].values():
            if c["status"] != "active":
                continue
            sets = [s for s in self.state["ad_sets"].values() if s["campaign_id"] == c["id"] and s["id"] in live_sets]
            if not sets:
                continue
            if c["daily_budget"]:
                for s in sets:
                    out[s["id"]] = c["daily_budget"] * 7 / len(sets)
            elif c["lifetime_budget"]:
                spent = c.get("spent", 0.0)
                for s in sets:
                    out[s["id"]] = max(0.0, c["lifetime_budget"] - spent) / len(sets)
            else:
                for s in sets:
                    out[s["id"]] = (s["daily_budget"] or 0) * 7
        return out

    def record_spend(self, ad_set_id: str, amount: float) -> None:
        s = self.state["ad_sets"][ad_set_id]
        s["spent"] = round(s.get("spent", 0.0) + amount, 2)
        c = self.state["campaigns"][s["campaign_id"]]
        c["spent"] = round(c.get("spent", 0.0) + amount, 2)
        self._save()


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * math.asin(math.sqrt(h))
