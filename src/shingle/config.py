"""Settings from environment / .env. No secrets are ever written to run bundles."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HARNESS_VERSION = "0.1.0"
PROMPT_VERSION = "p1"


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_url: str
    sandbox_backend: str  # auto | docker | local
    sandbox_image: str
    image_provider: str  # mock | openai
    payments_provider: str  # mock | stripe
    research_mode: str  # offline | online
    simulator_model: str  # model config name used for customer personas
    qa_model: str
    judge_models: list[str]
    sites_domain: str
    app_url: str
    secret_key: str
    keys: dict[str, str] = field(repr=False, default_factory=dict)

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    def key(self, name: str) -> str | None:
        return self.keys.get(name) or None


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default) or default


@lru_cache
def get_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    data_dir = Path(_env("SHINGLE_DATA_DIR", str(ROOT / "var"))).resolve()
    keys = {
        k: os.environ.get(k, "")
        for k in (
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENAI_COMPAT_API_KEY",
            "OPENAI_COMPAT_BASE_URL",
            "STRIPE_SECRET_KEY",
            "SEARCH_API_KEY",
        )
    }
    return Settings(
        data_dir=data_dir,
        database_url=_env("DATABASE_URL", f"sqlite:///{data_dir / 'shingle.db'}"),
        sandbox_backend=_env("SANDBOX_BACKEND", "auto"),
        sandbox_image=_env("SANDBOX_IMAGE", "shingle-sandbox:latest"),
        image_provider=_env("IMAGE_PROVIDER", "openai" if keys["OPENAI_API_KEY"] else "mock"),
        payments_provider=_env("PAYMENTS_PROVIDER", "stripe" if keys["STRIPE_SECRET_KEY"] else "mock"),
        research_mode=_env("RESEARCH_MODE", "offline"),
        simulator_model=_env("SIMULATOR_MODEL", "mock-simulator"),
        qa_model=_env("QA_MODEL", "mock-qa"),
        judge_models=[m.strip() for m in _env("JUDGE_MODELS", "mock-judge-a,mock-judge-b").split(",") if m.strip()],
        sites_domain=_env("SITES_DOMAIN", "localhost"),
        app_url=_env("APP_URL", "http://localhost:8000"),
        secret_key=_env("SECRET_KEY", "dev-only-change-me"),
        keys=keys,
    )
