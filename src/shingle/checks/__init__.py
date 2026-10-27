"""Automated checks: the objective layer. Results are context for graders, not the score."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ..bundle import key_pages
from ..sandbox.hosting import PreviewServer, frozen_platform
from ..sandbox.suppliers import catalog
from ..tasks.schema import Task
from .content import ad_compliance, deliverables_check, integrity, supplier_check
from .qa import run_qa
from .site import run_site_checks

CHECKS_VERSION = "c1"


def _supplier_claims(bundle: Path) -> tuple[list[str], str]:
    p = bundle / "commerce" / "suppliers.json"
    orders = json.loads(p.read_text()).get("orders", []) if p.exists() else []
    certs, mats = [], []
    for o in orders:
        for s in catalog():
            for prod in s["products"]:
                if prod["sku"] == o["sku"]:
                    certs += s["certifications"]
                    mats.append(prod["materials"])
    return certs, " ".join(mats)


def run_checks(bundle: Path, task: Task, qa_model: str = "mock-qa") -> dict:
    manifest = json.loads((bundle / "manifest.json").read_text())
    enabled = {c.value for c in task.checks}
    results: dict = {"deliverables": deliverables_check(manifest, task)}
    if (bundle / "site").exists():
        with tempfile.TemporaryDirectory() as tmp:
            plat = frozen_platform(bundle, Path(tmp) / "checks_scratch.json")
            srv = PreviewServer(plat)
            try:
                results |= run_site_checks(srv.url, plat, task, key_pages(task, bundle / "site"))
                if "product_qa" in enabled:
                    results["product_qa"] = run_qa(srv.url, plat, task, qa_model)
                results["ad_compliance"] = ad_compliance(bundle, task, plat)
            finally:
                srv.close()
    else:
        results["site_loads"] = {"status": "fail", "details": "site was never deployed"}
    certs, mats = _supplier_claims(bundle)
    results["integrity"] = integrity(bundle, task, certs, mats)
    results["supplier"] = supplier_check(bundle, task)
    if "checkout" not in enabled and results.get("checkout", {}).get("status") == "skip":
        results.pop("checkout", None)
    summary = {k: v.get("status") for k, v in results.items()}
    gate = all(summary.get(k) == "pass" for k in ("site_loads", "key_pages")) and \
        summary.get("checkout" if "checkout" in enabled else "forms", "pass") in ("pass", "skip")
    out = {"checks_version": CHECKS_VERSION, "summary": summary, "site_works_gate": gate,
           "counts": {s: sum(1 for v in summary.values() if v == s) for s in ("pass", "warn", "fail", "skip")}, "results": results}
    (bundle / "checks.json").write_text(json.dumps(out, indent=2))
    return out
