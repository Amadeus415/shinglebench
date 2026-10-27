"""Provider interface. Conversations use one neutral format; each provider translates it.

Neutral messages:
  {"role": "user", "content": str}
  {"role": "assistant", "content": str, "tool_calls": [{"id", "name", "args"}]}
  {"role": "tool", "tool_call_id": str, "name": str, "content": str, "is_error": bool}
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cached_input_tokens += other.cached_input_tokens


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    stop_reason: str = ""
    raw_model: str = ""
    raw: list | None = None  # provider-native assistant content, replayed unchanged (thinking blocks, signatures)


@dataclass
class ModelConfig:
    """One entry of models.yaml."""

    name: str  # public config name, e.g. "claude-opus-5-5"
    provider: str  # anthropic | openai | google | openai_compat | mock
    model: str  # provider model id (or mock profile)
    family: str  # for same-family judge flags: anthropic, openai, google, meta, mock-…
    max_output_tokens: int = 8000
    temperature: float | None = None
    context_window: int = 200_000
    price_in_per_mtok: float = 0.0
    price_out_per_mtok: float = 0.0
    price_cached_in_per_mtok: float | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    extra: dict = field(default_factory=dict)

    def cost(self, u: Usage) -> float:
        cached_price = self.price_cached_in_per_mtok if self.price_cached_in_per_mtok is not None else self.price_in_per_mtok
        fresh = max(0, u.input_tokens - u.cached_input_tokens)
        return (fresh * self.price_in_per_mtok + u.cached_input_tokens * cached_price + u.output_tokens * self.price_out_per_mtok) / 1e6


class ProviderError(Exception):
    def __init__(self, msg: str, retryable: bool = False):
        super().__init__(msg)
        self.retryable = retryable


class Provider:
    def __init__(self, cfg: ModelConfig):
        self.cfg = cfg

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:  # pragma: no cover
        raise NotImplementedError

    # shared HTTP with retries + exponential backoff and jitter
    def _post(self, url: str, headers: dict, body: dict, attempts: int = 6, timeout: float = 600) -> dict:
        delay = 2.0
        for i in range(attempts):
            try:
                r = httpx.post(url, headers=headers, json=body, timeout=timeout)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                err = ProviderError(f"transport: {e}", retryable=True)
            else:
                if r.status_code < 300:
                    return r.json()
                retry = r.status_code in (408, 409, 425, 429, 500, 502, 503, 504, 529)
                err = ProviderError(f"HTTP {r.status_code}: {r.text[:500]}", retryable=retry)
                if not retry:
                    raise err
                ra = r.headers.get("retry-after")
                if ra and ra.replace(".", "").isdigit():
                    delay = max(delay, float(ra))
            if i == attempts - 1:
                raise err
            time.sleep(delay + random.random())
            delay = min(delay * 2, 90)
        raise ProviderError("unreachable")
