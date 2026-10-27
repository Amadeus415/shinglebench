import json
import sys

import httpx
import pytest
from PIL import Image

from shingle.sandbox.ads import AdPlatform, AdsError
from shingle.sandbox.hosting import Hosting, frozen_platform
from shingle.sandbox.images import MockImages
from shingle.sandbox.payments import MockPayments, PaymentsError, StripeTestPayments
from shingle.sandbox.suppliers import Ledger, SupplierError, Suppliers, catalog
from shingle.sandbox.workspace import LocalShell, Workspace, WorkspaceError


def test_workspace_blocks_escape(tmp_path):
    ws = Workspace(tmp_path / "ws")
    ws.write("site/index.html", "hi")
    assert ws.read("site/index.html") == "hi"
    with pytest.raises(WorkspaceError):
        ws.write("../outside.txt", "x")
    with pytest.raises(WorkspaceError):
        ws.read("/etc/passwd/../../../etc/hosts")


@pytest.mark.skipif(sys.platform != "darwin", reason="seatbelt is macOS-only")
def test_local_shell_has_no_network(tmp_path):
    sh = LocalShell(Workspace(tmp_path / "ws"))
    assert "no-network" in sh.isolation
    r = sh.run("echo ok && curl -sS -m 5 https://example.com", timeout=20)
    assert "ok" in r.stdout and r.exit_code != 0
    r = sh.run("touch /Users/Shared/shingle_escape_test 2>&1; echo done")
    assert "not permitted" in (r.stdout + r.stderr).lower() or "denied" in (r.stdout + r.stderr).lower()


def test_payments_test_mode_only(tmp_path):
    with pytest.raises(PaymentsError):
        StripeTestPayments("sk_live_123")
    pay = MockPayments(tmp_path / "p.json")
    prod = pay.create_product("Thing")
    price = pay.create_price(prod["id"], 499)
    s = pay.create_session([{"price_id": price["id"], "quantity": 2}], "/success", "/")
    with pytest.raises(PaymentsError):
        pay.complete_session(s["id"], "a@b.c", "1234")
    done = pay.complete_session(s["id"], "a@b.c", "4242 4242 4242 4242")
    assert done["status"] == "complete" and pay.payments()[0]["amount"] == 998


def _site(ws_root, extra=""):
    (ws_root / "site").mkdir(parents=True, exist_ok=True)
    (ws_root / "site" / "index.html").write_text(f"<html><body><h1>Hi</h1>{extra}</body></html>")


def test_hosting_forms_checkout_and_freeze(tmp_path):
    ws = tmp_path / "ws"
    pay = MockPayments(tmp_path / "pay.json")
    pr = pay.create_price(pay.create_product("Pack")["id"], 400)
    _site(ws, f'<form method=post action="/api/checkout"><input type=hidden name=price_id value="{pr["id"]}"><button>Buy</button></form>')
    h = Hosting(ws, tmp_path, pay)
    info = h.deploy()
    url = info["url"]
    with httpx.Client(base_url=url, follow_redirects=False) as c:
        assert c.get("/").status_code == 200
        assert c.get("/missing").status_code == 404
        r = c.post("/api/forms/contact", data={"name": "A", "email": "a@b.c"})
        assert r.status_code == 200 and h.platform.state["forms"][0]["fields"]["name"] == "A"
        r = c.post("/api/checkout", data={"price_id": pr["id"]})
        assert r.status_code == 303 and r.headers["location"].startswith("/__checkout/")
        r2 = c.post(r.headers["location"], data={"email": "x@y.z", "card": "4242424242424242"})
        assert r2.status_code == 303 and pay.payments()
        assert c.put("/api/kv/count", content=b"3").status_code == 200 and c.get("/api/kv/count").json() == 3
    frozen = h.freeze(tmp_path / "frozen")
    h.close()
    assert frozen["frozen"]
    fp = frozen_platform(tmp_path / "frozen", tmp_path / "scratch.json")
    assert fp.handle("GET", "/", {}, b"").status == 200
    assert fp.handle("POST", "/api/checkout", {}, f"price_id={pr['id']}".encode()).status == 303


def test_ad_platform_validation(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "img.png").write_bytes(MockImages().generate("x", "square"))
    Image.new("RGB", (500, 900)).save(ws / "bad.png")
    ads = AdPlatform(tmp_path / "ads.json", ws, lambda: 0)
    with pytest.raises(AdsError):
        ads.create_campaign("c", "virality")
    c = ads.create_campaign("c", "leads", daily_budget=10)
    with pytest.raises(AdsError, match="unknown location"):
        ads.create_ad_set(c["id"], "s", {"geo": {"locations": ["city:US:atlantis"]}})
    with pytest.raises(AdsError, match="postcode"):
        ads.create_ad_set(c["id"], "s", {"geo": {"zips": ["US:9412"]}})
    s = ads.create_ad_set(c["id"], "s", {"geo": {"zips": ["US:94122"]}, "age_min": 25, "age_max": 45, "interests": ["cycling"]})
    good = {"headline": "Bike fixed at your door", "primary_text": "Mobile repair in the Sunset.", "cta": "BOOK_NOW", "image_path": "img.png", "landing_path": "/"}
    assert ads.create_ad(s["id"], "a", good)["image"]["ratio"] == "1:1"
    with pytest.raises(AdsError, match="max 40"):
        ads.create_ad(s["id"], "a", {**good, "headline": "x" * 41})
    with pytest.raises(AdsError, match="aspect|small"):
        ads.create_ad(s["id"], "a", {**good, "image_path": "bad.png"})
    with pytest.raises(AdsError, match="cta"):
        ads.create_ad(s["id"], "a", {**good, "cta": "CLICK_HERE"})
    hc = ads.create_campaign("h", "leads", daily_budget=5, special_ad_category="housing")
    with pytest.raises(AdsError, match="special ad category"):
        ads.create_ad_set(hc["id"], "s", {"geo": {"zips": ["US:94122"]}, "age_min": 25})
    assert ads.weekly_budgets() == {s["id"]: 70.0}


def test_suppliers_and_ledger(tmp_path):
    ledger = Ledger(tmp_path / "l.json", 1000, lambda: 0)
    sup = Suppliers(tmp_path / "s.json", ledger, lambda: 0)
    assert len(catalog()) >= 30
    craft = sup.search(family="candles")[-1]
    sku = craft["products"][0]["sku"]
    with pytest.raises(SupplierError, match="MOQ"):
        sup.quote(sku, 1, "US")
    q = sup.quote(sku, craft["moq"], "US")
    assert q["total"] == pytest.approx(q["product_subtotal"] + q["freight"] + q["packaging"])
    o = sup.place_order(sku, craft["moq"], "US")
    assert ledger.balance == pytest.approx(1000 - o["total"])
    with pytest.raises(SupplierError, match="insufficient"):
        sup.place_order(sku, craft["moq"] * 100, "US")
    assert sup.inventory() == {}  # not arrived yet


def test_mock_images_deterministic():
    a, b = MockImages().generate("hello", "landscape", 1), MockImages().generate("hello", "landscape", 1)
    assert a == b
    from io import BytesIO

    assert Image.open(BytesIO(a)).size == (1200, 628)
