"""Static hosting + a tiny "platform" (forms, checkout, key-value store).

Sites are static files the agent writes under `site/`. Dynamic behavior goes through
platform endpoints, the way Netlify Forms or Stripe Checkout work:

  POST /api/forms/<name>        store a form submission (form-encoded or JSON)
  POST /api/checkout            price_id[+quantity] or JSON {items:[...]} -> redirect to hosted checkout
  GET  /api/prices              the payments catalog as JSON
  GET|PUT /api/kv/<key>         small JSON key-value store for app state

`Platform.handle` is framework-free so the same code serves the live preview during an
episode and the frozen snapshot inside the grading app.
"""

from __future__ import annotations

import html
import json
import mimetypes
import shutil
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .payments import MockPayments, PaymentsError

MAX_BODY = 200_000


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


def _page(title: str, body: str) -> bytes:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>body{{font:16px/1.5 system-ui,sans-serif;max-width:520px;margin:48px auto;padding:0 16px;color:#1a1a1a}}
.badge{{display:inline-block;background:#fff3cd;border:1px solid #e0c36a;padding:2px 8px;border-radius:4px;font-size:12px;letter-spacing:.04em}}
input,button{{font:inherit;padding:10px;width:100%;box-sizing:border-box;margin:6px 0}}button{{background:#1a1a1a;color:#fff;border:0;border-radius:6px;cursor:pointer}}
.line{{display:flex;justify-content:space-between;border-bottom:1px solid #eee;padding:6px 0}}.err{{color:#b00020}}</style></head>
<body>{body}</body></html>""".encode()


def _money(cents: int, cur: str) -> str:
    return f"{cents / 100:,.2f} {cur.upper()}"


class Platform:
    def __init__(self, site_dir: Path | None, state_path: Path, payments: MockPayments, mode: str = "live"):
        self.site_dir = site_dir
        self.state_path = state_path
        self.payments = payments
        self.mode = mode
        self.lock = threading.Lock()
        self.state = {"forms": [], "kv": {}, "requests": 0}
        if state_path.exists():
            self.state = json.loads(state_path.read_text())

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2))

    # ------------------------------------------------------------------ http
    def handle(self, method: str, raw_path: str, headers: dict[str, str], body: bytes, source: str = "visitor") -> Response:
        url = urlparse(raw_path)
        path = url.path
        with self.lock:
            self.state["requests"] = self.state.get("requests", 0) + 1
        try:
            if path.startswith("/api/forms/") and method == "POST":
                return self._form(path.removeprefix("/api/forms/").strip("/") or "default", headers, body, source)
            if path == "/api/checkout" and method in ("POST", "GET"):
                data = self._parse(headers, body) if method == "POST" else {k: v[0] for k, v in parse_qs(url.query).items()}
                return self._checkout(data, headers)
            if path.startswith("/__checkout/"):
                return self._hosted_checkout(method, path.removeprefix("/__checkout/").strip("/"), headers, body, source)
            if path == "/api/prices":
                cat = [p for p in self.payments.catalog() if p["active"]]
                return Response(200, json.dumps(cat).encode(), {"Content-Type": "application/json"})
            if path.startswith("/api/kv/"):
                return self._kv(method, path.removeprefix("/api/kv/"), body)
            if method in ("GET", "HEAD"):
                return self._static(path)
            return Response(405, b"method not allowed", {"Content-Type": "text/plain"})
        except PaymentsError as e:
            return Response(400, _page("Checkout error", f"<p class=err>{html.escape(str(e))}</p><p><a href='/'>Back to site</a></p>"),
                            {"Content-Type": "text/html; charset=utf-8"})

    @staticmethod
    def _parse(headers: dict[str, str], body: bytes) -> dict:
        ctype = {k.lower(): v for k, v in headers.items()}.get("content-type", "")
        if "json" in ctype:
            try:
                data = json.loads(body or b"{}")
                return data if isinstance(data, dict) else {"_value": data}
            except json.JSONDecodeError:
                return {}
        return {k: (v[0] if len(v) == 1 else v) for k, v in parse_qs(body.decode(errors="replace")).items()}

    @staticmethod
    def _wants_json(headers: dict[str, str]) -> bool:
        h = {k.lower(): v for k, v in headers.items()}
        return "application/json" in h.get("accept", "") or "json" in h.get("content-type", "")

    def _form(self, name: str, headers: dict, body: bytes, source: str) -> Response:
        data = self._parse(headers, body)
        nxt = data.pop("_next", None)
        fields = {k: (str(v)[:2000] if not isinstance(v, list) else [str(x)[:500] for x in v]) for k, v in data.items()}
        with self.lock:
            self.state["forms"].append({"form": name[:60], "fields": fields, "ts": time.time(), "source": source, "mode": self.mode})
            self._save()
        if self._wants_json(headers):
            return Response(200, json.dumps({"ok": True, "form": name}).encode(), {"Content-Type": "application/json"})
        if nxt and str(nxt).startswith("/"):
            return Response(303, b"", {"Location": str(nxt)})
        for cand in ("thanks.html", "thank-you.html", "thanks/index.html"):
            if self.site_dir and (self.site_dir / cand).exists():
                return Response(303, b"", {"Location": "/" + cand.replace("index.html", "")})
        return Response(200, _page("Thanks", "<h1>Thanks!</h1><p>Your submission was received.</p><p><a href='/'>Back to site</a></p>"),
                        {"Content-Type": "text/html; charset=utf-8"})

    def _checkout(self, data: dict, headers: dict) -> Response:
        items = data.get("items")
        if isinstance(items, str):
            items = json.loads(items)
        if not items:
            items = [{"price_id": data.get("price_id") or data.get("price"), "quantity": data.get("quantity", 1)}]
        success = str(data.get("success_url") or "/success")
        cancel = str(data.get("cancel_url") or "/")
        s = self.payments.create_session(items, success_url=success, cancel_url=cancel)
        if self._wants_json(headers):
            return Response(200, json.dumps({"id": s["id"], "url": s["url"]}).encode(), {"Content-Type": "application/json"})
        return Response(303, b"", {"Location": s["url"]})

    def _hosted_checkout(self, method: str, sid: str, headers: dict, body: bytes, source: str) -> Response:
        s = self.payments.get_session(sid)
        err = ""
        if method == "POST":
            data = self._parse(headers, body)
            try:
                self.payments.complete_session(sid, str(data.get("email", "")), str(data.get("card", "")), source=source)
                target = s["success_url"]
                if target.startswith("/success") and not self._exists(target):
                    target = f"/__checkout/{sid}"
                return Response(303, b"", {"Location": target})
            except PaymentsError as e:
                err = f"<p class=err role=alert>{html.escape(str(e))}</p>"
        if s["status"] == "complete":
            return Response(200, _page("Payment complete", f"<span class=badge>TEST MODE</span><h1>Payment complete</h1><p>Total {_money(s['amount_total'], s['currency'])}. A receipt would be sent to {html.escape(s.get('customer_email', ''))}.</p><p><a href='/'>Return to site</a></p>"),
                            {"Content-Type": "text/html; charset=utf-8"})
        lines = "".join(f"<div class=line><span>{html.escape(li['name'])} × {li['quantity']}{' / ' + li['recurring']['interval'] if li['recurring'] else ''}</span><span>{_money(li['amount'], s['currency'])}</span></div>" for li in s["lines"])
        body_html = f"""<span class=badge>TEST MODE · no real charge</span><h1>Checkout</h1>{lines}
<div class=line><strong>Total</strong><strong>{_money(s['amount_total'], s['currency'])}</strong></div>{err}
<form method=post><label>Email<input name=email type=email required autocomplete=email></label>
<label>Card number<input name=card inputmode=numeric placeholder="4242 4242 4242 4242" required></label>
<button type=submit>Pay {_money(s['amount_total'], s['currency'])}</button></form>
<p><a href="{html.escape(s['cancel_url'])}">Cancel</a></p>"""
        return Response(200, _page("Checkout", body_html), {"Content-Type": "text/html; charset=utf-8"})

    def _kv(self, method: str, key: str, body: bytes) -> Response:
        key = key[:120]
        with self.lock:
            if method in ("PUT", "POST"):
                if len(self.state["kv"]) > 500:
                    return Response(413, b"kv store full")
                self.state["kv"][key] = json.loads(body or b"null")
                self._save()
                return Response(200, b'{"ok":true}', {"Content-Type": "application/json"})
            if method == "DELETE":
                self.state["kv"].pop(key, None)
                self._save()
                return Response(200, b'{"ok":true}', {"Content-Type": "application/json"})
            if key not in self.state["kv"]:
                return Response(404, b"null", {"Content-Type": "application/json"})
            return Response(200, json.dumps(self.state["kv"][key]).encode(), {"Content-Type": "application/json"})

    def _resolve(self, path: str) -> Path | None:
        if not self.site_dir:
            return None
        rel = path.lstrip("/")
        base = self.site_dir.resolve()
        for cand in (rel, f"{rel}/index.html" if rel else "index.html", f"{rel}.html"):
            p = (base / cand).resolve()
            if (p == base or base in p.parents) and p.is_file():
                return p
        return None

    def _exists(self, path: str) -> bool:
        return self._resolve(urlparse(path).path) is not None

    def _static(self, path: str) -> Response:
        p = self._resolve(path)
        if p is None:
            nf = self._resolve("/404.html")
            body = nf.read_bytes() if nf else _page("Not found", "<h1>404</h1><p>Page not found.</p>")
            return Response(404, body, {"Content-Type": "text/html; charset=utf-8"})
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        return Response(200, p.read_bytes(), {"Content-Type": ctype, "Cache-Control": "no-store"})


class PreviewServer:
    """Serves a Platform on 127.0.0.1:<random port> in a background thread."""

    def __init__(self, platform: Platform, port: int = 0):
        self.platform = platform
        plat = platform

        class Handler(BaseHTTPRequestHandler):
            def _go(self) -> None:
                n = min(int(self.headers.get("Content-Length") or 0), MAX_BODY)
                body = self.rfile.read(n) if n else b""
                src = self.headers.get("X-Shingle-Source", "visitor")
                r = plat.handle(self.command, self.path, dict(self.headers), body, source=src)
                self.send_response(r.status)
                for k, v in r.headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(r.body)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(r.body)

            do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = _go

            def log_message(self, *a) -> None:  # quiet
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.httpd.daemon_threads = True
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class Hosting:
    """Deploys workspace/site to versioned immutable copies; the preview always serves the latest."""

    def __init__(self, workspace_root: Path, run_dir: Path, payments: MockPayments):
        self.ws = workspace_root
        self.deploys = run_dir / "deploys"
        self.deploys.mkdir(parents=True, exist_ok=True)
        versions = sorted(int(p.name[1:]) for p in self.deploys.glob("v*") if p.name[1:].isdigit())
        self.version = versions[-1] if versions else 0
        self.platform = Platform(self.current_dir, run_dir / "state" / "platform.json", payments)
        self.server: PreviewServer | None = None

    @property
    def current_dir(self) -> Path | None:
        return self.deploys / f"v{self.version}" if self.version else None

    def start(self) -> str:
        if not self.server:
            self.server = PreviewServer(self.platform)
        return self.server.url

    def deploy(self, src: str = "site") -> dict:
        source = (self.ws / src).resolve()
        if self.ws.resolve() not in source.parents and source != self.ws.resolve():
            raise ValueError("deploy source must be inside the workspace")
        if not (source / "index.html").is_file():
            raise ValueError(f"{src}/index.html not found; the site root needs an index.html")
        files = [p for p in source.rglob("*") if p.is_file()]
        if len(files) > 2000 or sum(p.stat().st_size for p in files) > 80_000_000:
            raise ValueError("site too large (max 2000 files / 80 MB)")
        self.version += 1
        dest = self.deploys / f"v{self.version}"
        shutil.copytree(source, dest, ignore=shutil.ignore_patterns("node_modules", ".*"))
        self.platform.site_dir = dest
        url = self.start()
        pages = sorted(str(p.relative_to(dest)) for p in dest.rglob("*.html"))
        return {"version": self.version, "url": url, "pages": pages, "files": len(files)}

    def freeze(self, dest: Path) -> dict:
        """Static snapshot + payment catalog, enough to re-serve the site exactly as deployed."""
        if not self.current_dir:
            return {"frozen": False, "reason": "site was never deployed"}
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.current_dir, dest / "site")
        (dest / "platform.json").write_text(json.dumps(
            {"version": self.version, "payments": self.platform.payments.snapshot()}, indent=2))
        return {"frozen": True, "version": self.version}

    def close(self) -> None:
        if self.server:
            self.server.close()
            self.server = None


def frozen_platform(frozen_dir: Path, scratch_state: Path) -> Platform:
    """A Platform over a frozen snapshot; submissions go to a grader-scratch store."""
    snap = json.loads((frozen_dir / "platform.json").read_text())
    pay = MockPayments(scratch_state.with_suffix(".payments.json"))
    if not pay.state["prices"]:
        pay.state.update({"products": snap["payments"]["products"], "prices": snap["payments"]["prices"]})
    return Platform(frozen_dir / "site", scratch_state, pay, mode="frozen")
