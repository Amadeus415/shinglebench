"""Real model providers: Anthropic (official SDK), OpenAI + OpenAI-compatible (Chat Completions), Google (Gemini REST)."""

from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path

from .base import ModelConfig, Provider, ProviderError, ToolCall, Turn, Usage


def _parts(content) -> list[dict]:
    """User content may be a string or a list of {"type": "text"|"image", ...} parts."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    out = []
    for c in content:
        if c["type"] == "image":
            out.append({"type": "image", "b64": base64.b64encode(Path(c["path"]).read_bytes()).decode(), "mime": "image/png"})
        else:
            out.append(c)
    return out


def _group(messages: list[dict]) -> list[list[dict]]:
    """Group consecutive tool results so they can be returned in one turn."""
    out: list[list[dict]] = []
    for m in messages:
        if m["role"] == "tool" and out and out[-1][0]["role"] == "tool":
            out[-1].append(m)
        else:
            out.append([m])
    return out


# ------------------------------------------------------------------ Anthropic
class AnthropicProvider(Provider):
    """Messages API via the official SDK. No refusal fallback: a different model answering would confound the benchmark."""

    def __init__(self, cfg: ModelConfig, key: str):
        super().__init__(cfg)
        import anthropic

        self.anthropic = anthropic
        self.client = anthropic.Anthropic(api_key=key, max_retries=6, timeout=900)

    def _messages(self, messages: list[dict]) -> list[dict]:
        out = []
        for grp in _group(messages):
            m = grp[0]
            if m["role"] == "user":
                out.append({"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": x["mime"], "data": x["b64"]}} if x["type"] == "image" else x
                    for x in _parts(m["content"])]})
            elif m["role"] == "assistant":
                raw = (m.get("raw") or {})
                if raw.get("provider") == "anthropic":
                    out.append({"role": "assistant", "content": raw["content"]})
                    continue
                blocks = [{"type": "text", "text": m["content"]}] if m.get("content") else []
                blocks += [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["args"]} for c in m.get("tool_calls", [])]
                out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": "(no output)"}]})
            else:  # all tool results of one turn in a single user message
                out.append({"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": t["tool_call_id"], "content": t["content"] or "(empty)", "is_error": bool(t.get("is_error"))}
                    for t in grp]})
        return out

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        a = self.anthropic
        try:
            resp = self.client.messages.create(
                model=self.cfg.model,
                max_tokens=self.cfg.max_output_tokens,
                system=[{"type": "text", "text": system}],
                messages=self._messages(messages),
                tools=tools,
                cache_control={"type": "ephemeral"},
                output_config={"effort": self.cfg.extra.get("effort", "high")},
            )
        except (a.RateLimitError, a.InternalServerError, a.APIConnectionError) as e:
            raise ProviderError(f"anthropic: {e}", retryable=True) from e
        except a.APIStatusError as e:
            raise ProviderError(f"anthropic: {e.status_code} {e.message}", retryable=e.status_code >= 500) from e
        text = "".join(b.text for b in resp.content if b.type == "text")
        calls = [ToolCall(b.id, b.name, dict(b.input)) for b in resp.content if b.type == "tool_use"]
        u = resp.usage
        cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(u, "cache_creation_input_tokens", 0) or 0
        usage = Usage(input_tokens=u.input_tokens + cache_read + cache_write, output_tokens=u.output_tokens, cached_input_tokens=cache_read)
        raw = [b.model_dump(mode="json", exclude_none=True) for b in resp.content]
        return Turn(text, calls, usage, resp.stop_reason or "", resp.model, raw=raw)


# ------------------------------------------------------------------ OpenAI / compatible
class OpenAIChatProvider(Provider):
    def __init__(self, cfg: ModelConfig, key: str, base_url: str = "https://api.openai.com/v1"):
        super().__init__(cfg)
        self.key = key
        self.base_url = base_url.rstrip("/")

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        msgs: list[dict] = [{"role": "system", "content": system}]
        for m in messages:
            if m["role"] == "user":
                msgs.append({"role": "user", "content": m["content"] if isinstance(m["content"], str) else [
                    {"type": "image_url", "image_url": {"url": f"data:{x['mime']};base64,{x['b64']}"}} if x["type"] == "image" else x
                    for x in _parts(m["content"])]})
            elif m["role"] == "assistant":
                am = {"role": "assistant", "content": m.get("content") or None}
                if m.get("tool_calls"):
                    am["tool_calls"] = [{"id": c["id"], "type": "function",
                                         "function": {"name": c["name"], "arguments": json.dumps(c["args"])}} for c in m["tool_calls"]]
                msgs.append(am)
            else:
                msgs.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"] or "(empty)"})
        body = {"model": self.cfg.model, "messages": msgs, "max_completion_tokens": self.cfg.max_output_tokens,
                "tools": [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}} for t in tools]}
        if self.cfg.temperature is not None:
            body["temperature"] = self.cfg.temperature
        body.update(self.cfg.extra.get("body", {}))
        data = self._post(f"{self.base_url}/chat/completions", {"Authorization": f"Bearer {self.key}"}, body)
        choice = data["choices"][0]
        msg = choice["message"]
        calls = []
        for c in msg.get("tool_calls") or []:
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": c["function"].get("arguments", "")}
            calls.append(ToolCall(c["id"], c["function"]["name"], args))
        u = data.get("usage") or {}
        usage = Usage(u.get("prompt_tokens", 0), u.get("completion_tokens", 0),
                      (u.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
        return Turn(msg.get("content") or "", calls, usage, choice.get("finish_reason", ""), data.get("model", ""))


# ------------------------------------------------------------------ Google Gemini
def _gemini_schema(s):
    if isinstance(s, dict):
        return {k: _gemini_schema(v) for k, v in s.items() if k not in ("additionalProperties",)}
    if isinstance(s, list):
        return [_gemini_schema(x) for x in s]
    return s


class GoogleProvider(Provider):
    def __init__(self, cfg: ModelConfig, key: str):
        super().__init__(cfg)
        self.key = key

    def complete(self, system: str, messages: list[dict], tools: list[dict]) -> Turn:
        contents = []
        for grp in _group(messages):
            m = grp[0]
            if m["role"] == "user":
                contents.append({"role": "user", "parts": [
                    {"inline_data": {"mime_type": x["mime"], "data": x["b64"]}} if x["type"] == "image" else {"text": x["text"]}
                    for x in _parts(m["content"])]})
            elif m["role"] == "assistant":
                raw = m.get("raw") or {}
                if raw.get("provider") == "google":
                    contents.append({"role": "model", "parts": raw["content"]})
                    continue
                parts = [{"text": m["content"]}] if m.get("content") else []
                parts += [{"functionCall": {"name": c["name"], "args": c["args"]}} for c in m.get("tool_calls", [])]
                contents.append({"role": "model", "parts": parts or [{"text": "(no output)"}]})
            else:
                contents.append({"role": "user", "parts": [
                    {"functionResponse": {"name": t["name"], "response": {"content": t["content"], "is_error": bool(t.get("is_error"))}}} for t in grp]})
        body = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents,
                "tools": [{"functionDeclarations": [{"name": t["name"], "description": t["description"],
                                                     "parameters": _gemini_schema(t["input_schema"])} for t in tools]}],
                "generationConfig": {"maxOutputTokens": self.cfg.max_output_tokens}}
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.cfg.model}:generateContent"
        data = self._post(url, {"x-goog-api-key": self.key}, body)
        cand = (data.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        calls = [ToolCall(f"call_{uuid.uuid4().hex[:12]}", p["functionCall"]["name"], p["functionCall"].get("args") or {})
                 for p in parts if "functionCall" in p]
        u = data.get("usageMetadata") or {}
        usage = Usage(u.get("promptTokenCount", 0), u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0),
                      u.get("cachedContentTokenCount", 0))
        return Turn(text, calls, usage, cand.get("finishReason", ""), self.cfg.model, raw=parts)
