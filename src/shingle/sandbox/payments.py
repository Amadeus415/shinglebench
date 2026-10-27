"""Payments in test mode only.

MockPayments is the default and needs nothing. StripeTestPayments talks to the real Stripe
API but refuses any key that is not a test key (`sk_test_`), so no real charge is possible.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import httpx

TEST_CARDS = {"4242424242424242": "succeeded", "4000000000000002": "declined"}


class PaymentsError(Exception):
    pass


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:14]}"


class MockPayments:
    name = "mock"

    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path
        self.state = {"products": {}, "prices": {}, "sessions": {}, "payments": []}
        if state_path and state_path.exists():
            self.state = json.loads(state_path.read_text())

    def _save(self) -> None:
        if self.state_path:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(self.state, indent=2))

    # catalog -------------------------------------------------------------
    def create_product(self, name: str, description: str = "") -> dict:
        if not name.strip():
            raise PaymentsError("product name is required")
        p = {"id": _id("prod"), "name": name.strip()[:120], "description": description[:500], "active": True}
        self.state["products"][p["id"]] = p
        self._save()
        return p

    def create_price(self, product_id: str, unit_amount: int, currency: str = "usd", interval: str | None = None, nickname: str = "") -> dict:
        if product_id not in self.state["products"]:
            raise PaymentsError(f"no such product: {product_id}")
        if not isinstance(unit_amount, int) or unit_amount < 50:
            raise PaymentsError("unit_amount must be an integer in minor units (cents) and at least 50")
        if interval not in (None, "week", "month", "year"):
            raise PaymentsError("interval must be one of week, month, year or omitted")
        if len(currency) != 3:
            raise PaymentsError("currency must be a 3-letter ISO code")
        pr = {
            "id": _id("price"), "product": product_id, "unit_amount": unit_amount, "currency": currency.lower(),
            "recurring": {"interval": interval} if interval else None, "nickname": nickname[:80], "active": True,
        }
        self.state["prices"][pr["id"]] = pr
        self._save()
        return pr

    def update_price(self, price_id: str, active: bool) -> dict:
        pr = self.get_price(price_id)
        pr["active"] = active
        self._save()
        return pr

    def get_price(self, price_id: str) -> dict:
        if price_id not in self.state["prices"]:
            raise PaymentsError(f"no such price: {price_id}")
        return self.state["prices"][price_id]

    def catalog(self) -> list[dict]:
        out = []
        for pr in self.state["prices"].values():
            prod = self.state["products"].get(pr["product"], {})
            out.append({**pr, "product_name": prod.get("name", ""), "product_description": prod.get("description", "")})
        return out

    # checkout --------------------------------------------------------------
    def create_session(self, items: list[dict], success_url: str, cancel_url: str, metadata: dict | None = None) -> dict:
        if not items:
            raise PaymentsError("checkout needs at least one line item")
        lines, total, currency = [], 0, None
        for it in items:
            pr = self.get_price(str(it.get("price_id") or it.get("price")))
            if not pr["active"]:
                raise PaymentsError(f"price {pr['id']} is inactive")
            qty = max(1, min(int(it.get("quantity", 1) or 1), 99))
            if currency and pr["currency"] != currency:
                raise PaymentsError("all line items must share a currency")
            currency = pr["currency"]
            lines.append({"price": pr["id"], "quantity": qty, "amount": pr["unit_amount"] * qty,
                          "name": self.state["products"][pr["product"]]["name"], "recurring": pr["recurring"]})
            total += pr["unit_amount"] * qty
        s = {"id": _id("cs_test"), "lines": lines, "amount_total": total, "currency": currency, "status": "open",
             "success_url": success_url, "cancel_url": cancel_url, "metadata": metadata or {}, "created": time.time()}
        s["url"] = f"/__checkout/{s['id']}"
        self.state["sessions"][s["id"]] = s
        self._save()
        return s

    def get_session(self, sid: str) -> dict:
        if sid not in self.state["sessions"]:
            raise PaymentsError("no such checkout session")
        return self.state["sessions"][sid]

    def complete_session(self, sid: str, email: str, card: str, source: str = "visitor") -> dict:
        s = self.get_session(sid)
        if s["status"] == "complete":
            return s
        card = "".join(ch for ch in card if ch.isdigit())
        outcome = TEST_CARDS.get(card)
        if outcome is None:
            raise PaymentsError("Test mode: use card 4242 4242 4242 4242")
        if "@" not in email:
            raise PaymentsError("A valid email is required")
        if outcome == "declined":
            raise PaymentsError("Your card was declined (test card)")
        s["status"] = "complete"
        s["customer_email"] = email
        self.state["payments"].append({"id": _id("pi_test"), "session": sid, "amount": s["amount_total"],
                                       "currency": s["currency"], "email": email, "source": source, "ts": time.time()})
        self._save()
        return s

    def payments(self) -> list[dict]:
        return list(self.state["payments"])

    def snapshot(self) -> dict:
        return {"products": self.state["products"], "prices": self.state["prices"]}


class StripeTestPayments(MockPayments):
    """Mirrors products/prices into Stripe test mode; checkout redirects to Stripe's hosted page."""

    name = "stripe-test"

    def __init__(self, key: str, state_path: Path | None = None):
        if not key.startswith("sk_test_"):
            raise PaymentsError("Refusing non-test Stripe key: only sk_test_ keys are allowed")
        super().__init__(state_path)
        self.http = httpx.Client(base_url="https://api.stripe.com/v1", auth=(key, ""), timeout=30)

    def _post(self, path: str, data: dict) -> dict:
        r = self.http.post(path, data=data)
        if r.status_code >= 400:
            raise PaymentsError(f"stripe: {r.json().get('error', {}).get('message', r.text)}")
        return r.json()

    def create_product(self, name: str, description: str = "") -> dict:
        p = super().create_product(name, description)
        sp = self._post("/products", {"name": p["name"], "description": p["description"] or p["name"]})
        p["stripe_id"] = sp["id"]
        self._save()
        return p

    def create_price(self, product_id, unit_amount, currency="usd", interval=None, nickname=""):
        pr = super().create_price(product_id, unit_amount, currency, interval, nickname)
        data = {"product": self.state["products"][product_id]["stripe_id"], "unit_amount": unit_amount, "currency": pr["currency"]}
        if interval:
            data["recurring[interval]"] = interval
        pr["stripe_id"] = self._post("/prices", data)["id"]
        self._save()
        return pr

    def create_session(self, items, success_url, cancel_url, metadata=None):
        s = super().create_session(items, success_url, cancel_url, metadata)
        data = {"success_url": success_url, "cancel_url": cancel_url,
                "mode": "subscription" if any(li["recurring"] for li in s["lines"]) else "payment"}
        for i, li in enumerate(s["lines"]):
            data[f"line_items[{i}][price]"] = self.state["prices"][li["price"]]["stripe_id"]
            data[f"line_items[{i}][quantity]"] = li["quantity"]
        s["url"] = self._post("/checkout/sessions", data)["url"]
        self._save()
        return s


def make_payments(provider: str, key: str | None, state_path: Path | None) -> MockPayments:
    if provider == "stripe" and key:
        return StripeTestPayments(key, state_path)
    return MockPayments(state_path)
