"""Mock supplier catalog, quotes, samples and production orders, plus the episode cash ledger."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

from ..config import ROOT

TRANSIT_DAYS = {"value": 28, "mid": 12, "craft": 4}
DESTS = ("US", "EU", "UK", "AU", "other")


class SupplierError(Exception):
    pass


@lru_cache
def catalog() -> list[dict]:
    return json.loads((ROOT / "data" / "suppliers.json").read_text())


def _sku(sku: str) -> tuple[dict, dict]:
    for s in catalog():
        for p in s["products"]:
            if p["sku"] == sku:
                return s, p
    raise SupplierError(f"unknown sku '{sku}'")


class Ledger:
    """Simulated cash. Every movement is an entry; the balance can't go negative for purchases."""

    def __init__(self, state_path: Path, starting_cash: float, clock):
        self.state_path = state_path
        self.clock = clock
        self.state = {"starting_cash": starting_cash, "entries": []}
        if state_path.exists():
            self.state = json.loads(state_path.read_text())

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2))

    @property
    def balance(self) -> float:
        return round(self.state["starting_cash"] + sum(e["amount"] for e in self.state["entries"]), 2)

    def post(self, kind: str, amount: float, memo: str, allow_negative: bool = False) -> dict:
        if amount < 0 and not allow_negative and self.balance + amount < -0.005:
            raise SupplierError(f"insufficient simulated cash: balance ${self.balance:,.2f}, need ${-amount:,.2f}")
        e = {"week": self.clock(), "kind": kind, "amount": round(amount, 2), "memo": memo[:200]}
        self.state["entries"].append(e)
        self._save()
        return e

    def totals(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for e in self.state["entries"]:
            out[e["kind"]] = round(out.get(e["kind"], 0.0) + e["amount"], 2)
        return out


class Suppliers:
    def __init__(self, state_path: Path, ledger: Ledger, clock, market_country: str = "US"):
        self.state_path = state_path
        self.ledger = ledger
        self.clock = clock
        self.market_country = market_country
        self.state = {"samples": [], "orders": [], "quotes": 0}
        if state_path.exists():
            self.state = json.loads(state_path.read_text())

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2))

    def search(self, query: str = "", family: str = "") -> list[dict]:
        q = query.lower()
        out = []
        for s in catalog():
            if family and s["family"] != family:
                continue
            hay = f"{s['family']} {s['name']} {' '.join(p['name'] + ' ' + p['spec'] for p in s['products'])}".lower()
            if q and not all(w in hay for w in q.split()):
                continue
            out.append({k: s[k] for k in ("id", "name", "family", "region", "ships_from", "moq", "lead_time_days", "rating",
                                          "defect_rate_pct", "sample_cost_usd", "sample_days", "certifications",
                                          "payment_terms", "notes")}
                       | {"products": [{k: p[k] for k in ("sku", "name", "spec", "materials", "price_breaks", "unit_weight_kg")}
                                       for p in s["products"]]})
        return out

    def families(self) -> list[str]:
        return sorted({s["family"] for s in catalog()})

    def quote(self, sku: str, quantity: int, destination: str) -> dict:
        s, p = _sku(sku)
        if destination not in DESTS:
            raise SupplierError(f"destination must be one of {', '.join(DESTS)}")
        if quantity < s["moq"]:
            raise SupplierError(f"quantity {quantity} is below MOQ {s['moq']} for {s['name']}")
        unit = next(b["unit_cost"] for b in sorted(p["price_breaks"], key=lambda b: -b["min_qty"]) if quantity >= b["min_qty"])
        freight = round(p["unit_weight_kg"] * quantity * s["freight_per_kg_usd"][destination], 2)
        packaging = round(p["packaging_cost"] * quantity, 2)
        subtotal = round(unit * quantity, 2)
        total = round(subtotal + freight + packaging, 2)
        days = s["lead_time_days"] + TRANSIT_DAYS[s["profile"]]
        self.state["quotes"] += 1
        self._save()
        return {"sku": sku, "supplier": s["name"], "quantity": quantity, "unit_cost": unit, "product_subtotal": subtotal,
                "freight": freight, "packaging": packaging, "total": total, "landed_unit_cost": round(total / quantity, 2),
                "production_days": s["lead_time_days"], "transit_days": TRANSIT_DAYS[s["profile"]],
                "arrives_in_weeks": math.ceil(days / 7), "payment_terms": s["payment_terms"]}

    def order_sample(self, sku: str) -> dict:
        s, p = _sku(sku)
        self.ledger.post("sample", -s["sample_cost_usd"], f"sample {sku}")
        rec = {"sku": sku, "supplier": s["name"], "ordered_week": self.clock(),
               "arrives_week": self.clock() + math.ceil(s["sample_days"] / 7), "cost": s["sample_cost_usd"],
               "report": (f"Sample of '{p['name']}': finish and dimensions match spec ({p['spec']}). "
                          + ("Minor glaze/print inconsistencies observed; expect some batch variance." if s["defect_rate_pct"] >= 3
                             else "Build quality is consistent."))}
        self.state["samples"].append(rec)
        self._save()
        return {k: v for k, v in rec.items() if k != "report"} | {"note": "Sample report becomes available in the week it arrives."}

    def place_order(self, sku: str, quantity: int, destination: str, notes: str = "") -> dict:
        q = self.quote(sku, quantity, destination)
        self.ledger.post("inventory", -q["total"], f"PO {sku} x{quantity}")
        rec = {**q, "ordered_week": self.clock(), "arrives_week": self.clock() + q["arrives_in_weeks"],
               "notes": notes[:300], "id": f"po_{len(self.state['orders']) + 1:03d}"}
        self.state["orders"].append(rec)
        self._save()
        return rec

    def samples_ready(self) -> list[dict]:
        return [s for s in self.state["samples"] if s["arrives_week"] <= self.clock()]

    def inventory(self) -> dict[str, int]:
        """Units on hand that have arrived, minus units sold (tracked in state['sold'])."""
        inv: dict[str, int] = {}
        for o in self.state["orders"]:
            if o["arrives_week"] <= self.clock():
                inv[o["sku"]] = inv.get(o["sku"], 0) + o["quantity"]
        for sku, n in self.state.get("sold", {}).items():
            inv[sku] = inv.get(sku, 0) - n
        return inv

    def incoming(self) -> list[dict]:
        return [{"sku": o["sku"], "quantity": o["quantity"], "arrives_week": o["arrives_week"]}
                for o in self.state["orders"] if o["arrives_week"] > self.clock()]

    def record_sales(self, units: int) -> int:
        """Fulfill `units` from on-hand stock (any SKU, FIFO). Returns units actually fulfilled."""
        inv = self.inventory()
        sold = self.state.setdefault("sold", {})
        done = 0
        for sku, n in inv.items():
            take = min(n, units - done)
            if take > 0:
                sold[sku] = sold.get(sku, 0) + take
                done += take
        self._save()
        return done
