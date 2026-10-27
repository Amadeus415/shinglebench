"""Model registry: config/models.yaml -> Provider instances."""

from __future__ import annotations

import os
from functools import lru_cache

import yaml

from ...config import ROOT, get_settings
from .base import ModelConfig, Provider, ProviderError, ToolCall, Turn, Usage
from .mock import MockModel


@lru_cache
def model_configs() -> dict[str, ModelConfig]:
    raw = yaml.safe_load((ROOT / "config" / "models.yaml").read_text())["models"]
    out = {}
    for m in raw:
        m = dict(m)
        base_url_env = m.pop("base_url_env", None)
        if base_url_env:
            m["extra"] = {**m.get("extra", {}), "base_url_env": base_url_env}
        out[m["name"]] = ModelConfig(**m)
    return out


def get_model(name: str) -> ModelConfig:
    cfgs = model_configs()
    if name not in cfgs:
        raise KeyError(f"unknown model '{name}'; add it to config/models.yaml (known: {', '.join(cfgs)})")
    return cfgs[name]


def _key(cfg: ModelConfig) -> str:
    return get_settings().key(cfg.api_key_env or "") or os.environ.get(cfg.api_key_env or "", "")


def has_credentials(cfg: ModelConfig) -> bool:
    return cfg.provider == "mock" or bool(_key(cfg))


def make_provider(cfg: ModelConfig, seed: int = 0) -> Provider:
    if cfg.provider == "mock":
        return MockModel(cfg, seed=seed)
    key = _key(cfg)
    if not key:
        raise ProviderError(f"{cfg.name}: {cfg.api_key_env} is not set")
    if cfg.provider == "anthropic":
        from .real import AnthropicProvider

        return AnthropicProvider(cfg, key)
    if cfg.provider == "openai":
        from .real import OpenAIChatProvider

        return OpenAIChatProvider(cfg, key)
    if cfg.provider == "openai_compat":
        from .real import OpenAIChatProvider

        base = os.environ.get(cfg.extra.get("base_url_env", "OPENAI_COMPAT_BASE_URL"), "") or cfg.base_url
        if not base:
            raise ProviderError(f"{cfg.name}: set {cfg.extra.get('base_url_env', 'OPENAI_COMPAT_BASE_URL')}")
        return OpenAIChatProvider(cfg, key, base_url=base)
    if cfg.provider == "google":
        from .real import GoogleProvider

        return GoogleProvider(cfg, key)
    raise ProviderError(f"unknown provider '{cfg.provider}'")


__all__ = ["ModelConfig", "Provider", "ProviderError", "ToolCall", "Turn", "Usage", "model_configs", "get_model", "make_provider", "has_credentials"]
