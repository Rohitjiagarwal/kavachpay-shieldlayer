"""Chat model clients.

Chat clients call their provider directly; the Shield funnel runs in-process in
app/pipeline.py (before the model) and output checks run after it.

Selection (see chat_model()):
  1. a visitor's own Gemini key on this request (X-Gemini-Key)  -> Gemini
  2. CHAT_PROVIDER=gemini + GEMINI_API_KEY (the hosted demo)    -> Gemini
  3. ANTHROPIC_API_KEY                                          -> Claude
  4. CHAT_PROVIDER=auto|ollama and an installed Ollama model    -> Ollama
  5. otherwise a deterministic offline stub (tests, CI)

The stub never *obeys* text inside sources (it only extracts), which mirrors
the defended behaviour, so the whole pipeline stays testable offline.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from app.settings import SETTINGS


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[dict] = field(default_factory=list)  # [{id,name,input}]
    stop_reason: str = "end_turn"
    usage: dict = field(default_factory=lambda: {"input_tokens": 0, "output_tokens": 0})


class StubChatModel:
    """Offline stand-in. Deterministic, no network, never obeys injected text."""

    provider = "stub"

    def __init__(self, model: str = "stub-chat"):
        self.model = model

    def complete(self, system: str, messages: list[dict], tools: list[dict] | None = None,
                 tool_results: dict | None = None) -> LLMResponse:
        last_user = ""
        for m in reversed(messages):
            if m["role"] == "user":
                last_user = m["content"] if isinstance(m["content"], str) else str(m["content"])
                break
        q = last_user.lower()
        um = re.search(r"User: (.*)\Z", last_user, re.S)
        if um:
            q = um.group(1).lower()

        if re.fullmatch(r"\s*(hi+|hello|hey+|namaste|yo|good (morning|afternoon|evening))\W*", q):
            return LLMResponse(text="Hey! I'm Kavi, your KavachPay assistant. How can I help today?")

        # If we already ran tools this turn, answer from their results.
        if tool_results:
            parts = []
            for name, res in tool_results.items():
                parts.append(f"{name}: {json.dumps(res)[:300]}")
            return LLMResponse(text="Here is what I found [tool]: " + "; ".join(parts))

        m = re.search(r"order\s*#?\s*(\d{3,})", q)
        # refund is checked before plain order lookup
        if "refund" in q and m:
            amt = 0.0
            am = re.search(r"\$\s?(\d{1,6})(?:\.\d+)?", q)
            if am:
                amt = float(am.group(1))
            return LLMResponse(
                stop_reason="tool_use",
                tool_calls=[{"id": "t1", "name": "request_refund",
                             "input": {"order_id": int(m.group(1)), "amount_usd": amt, "reason": "customer request"}}],
            )
        # order lookup
        if m and ("order" in q or "status" in q or "where" in q):
            return LLMResponse(
                stop_reason="tool_use",
                tool_calls=[{"id": "t1", "name": "get_order", "input": {"order_id": int(m.group(1))}}],
            )
        if "my orders" in q or "list my orders" in q:
            return LLMResponse(stop_reason="tool_use",
                               tool_calls=[{"id": "t1", "name": "get_my_orders", "input": {}}])

        # otherwise answer from retrieved context embedded in the system/user blocks
        ctx = _extract_sources(messages)
        if ctx:
            first = ctx[0]
            snippet = re.sub(r"\s+", " ", first["text"])[:240]
            return LLMResponse(text=f"{snippet} [{first['id']}]")
        return LLMResponse(text="I don't have that information. Would you like me to connect you to a human?")


def _extract_sources(messages: list[dict]) -> list[dict]:
    """Pull [cN] labelled sources the pipeline injected, for the stub to quote."""
    out = []
    for m in messages:
        content = m["content"] if isinstance(m["content"], str) else ""
        for mm in re.finditer(r"\[(c\d+)\]\s*(.*?)(?=\n\[c\d+\]|\Z)", content, re.S):
            out.append({"id": mm.group(1), "text": mm.group(2).strip()})
    return out


class AnthropicChatModel:
    """Real Claude client (direct to Anthropic)."""

    provider = "anthropic"

    def __init__(self, model: str):
        import anthropic  # type: ignore

        self.model = model
        self._client = anthropic.Anthropic(api_key=SETTINGS.anthropic_key)

    def complete(self, system: str, messages: list[dict], tools: list[dict] | None = None,
                 tool_results: dict | None = None) -> LLMResponse:
        kwargs: dict[str, Any] = dict(
            model=self.model, max_tokens=4096, system=system, messages=messages,
            output_config={"effort": "medium"},
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = {"type": "auto"}
        resp = self._client.messages.create(**kwargs)
        text, calls = "", []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text += block.text
            elif getattr(block, "type", None) == "tool_use":
                calls.append({"id": block.id, "name": block.name, "input": block.input})
        return LLMResponse(
            text=text, tool_calls=calls, stop_reason=resp.stop_reason or "end_turn",
            usage={"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
        )


PREFERRED_CHAT_MODELS = ["qwen2.5:7b", "llama3.1:8b", "qwen2.5:3b", "llama3.2:3b",
                         "gemma2:2b", "phi3.5", "qwen2.5:1.5b", "llama3.2:1b"]
_resolved_model: str | None = None


def resolve_ollama_model() -> str | None:
    """Pick the best installed chat model. Coder models are a last resort."""
    global _resolved_model
    if SETTINGS.chat_ollama_model and SETTINGS.chat_ollama_model != "auto":
        return SETTINGS.chat_ollama_model
    if _resolved_model:
        return _resolved_model
    try:
        import httpx

        r = httpx.get(f"{SETTINGS.ollama_host}/api/tags", timeout=2.0)
        names = [m["name"] for m in r.json().get("models", [])]
    except Exception:  # noqa: BLE001
        return None
    if not names:
        return None
    for pref in PREFERRED_CHAT_MODELS:
        for n in names:
            if n == pref or n.startswith(pref + "-") or n == pref + ":latest":
                _resolved_model = n
                return n
    non_coder = [n for n in names if "coder" not in n and "embed" not in n]
    _resolved_model = (non_coder or names)[0]
    return _resolved_model


class OllamaChatModel:
    """Local chat model via Ollama's /api/chat. Tool results arrive as data blocks
    in the prompt (tools are planned and executed in code, never by the model)."""

    provider = "ollama"

    def __init__(self, model: str):
        self.model = model

    supports_progress = True

    def complete(self, system: str, messages: list[dict], tools: list[dict] | None = None,
                 tool_results: dict | None = None, on_progress=None) -> LLMResponse:
        """`on_progress(phase, tokens)` (optional) streams generation progress:
        phase is "prompt" until the first token, then "writing". The reply text
        itself is only returned at the end, after it is complete."""
        import httpx

        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}] + [
                {"role": m["role"], "content": m["content"] if isinstance(m["content"], str) else str(m["content"])}
                for m in messages
            ],
            "stream": False,
            "keep_alive": "30m",
            "options": {"temperature": 0.3, "num_ctx": 4096, "top_p": 0.9, "num_predict": 380},
        }
        if on_progress is not None:
            return self._complete_streaming(payload, on_progress)
        r = httpx.post(f"{SETTINGS.ollama_host}/api/chat", json=payload, timeout=180.0)
        r.raise_for_status()
        j = r.json()
        return LLMResponse(
            text=(j.get("message") or {}).get("content", "").strip(),
            usage={"input_tokens": j.get("prompt_eval_count", 0),
                   "output_tokens": j.get("eval_count", 0)},
        )


    def _complete_streaming(self, payload: dict, on_progress) -> LLMResponse:
        import json
        import time

        import httpx

        parts: list[str] = []
        tokens, last, final = 0, 0.0, {}
        on_progress("prompt", 0)
        with httpx.stream("POST", f"{SETTINGS.ollama_host}/api/chat",
                          json={**payload, "stream": True}, timeout=180.0) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if not line:
                    continue
                j = json.loads(line)
                piece = (j.get("message") or {}).get("content", "")
                if piece:
                    parts.append(piece)
                    tokens += 1
                    now = time.monotonic()
                    if tokens == 1 or now - last > 0.25:
                        last = now
                        on_progress("writing", tokens)
                if j.get("done"):
                    final = j
        return LLMResponse(
            text="".join(parts).strip(),
            usage={"input_tokens": final.get("prompt_eval_count", 0),
                   "output_tokens": final.get("eval_count", tokens)},
        )


GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiChatModel:
    """Gemini via the REST API (no SDK). Like the Ollama client it only writes
    the reply: tools are planned and executed in code before it is called.

    The key goes in the `x-goog-api-key` header, never in the URL, so it cannot
    leak into error messages or logs."""

    provider = "gemini"
    supports_progress = True

    def __init__(self, model: str, api_key: str, visitor_key: bool = False, timeout: float = 45.0):
        if not api_key:
            raise ValueError("Gemini API key is empty")
        self.model = f"{model} (visitor key)" if visitor_key else model
        self._model = model
        self._key = api_key
        self.timeout = timeout
        self._base = (os.environ.get("GEMINI_BASE_URL") or GEMINI_BASE).rstrip("/")

    def _body(self, system: str, messages: list[dict]) -> dict:
        contents: list[dict] = []
        for m in messages:
            role = "model" if m["role"] == "assistant" else "user"
            text = m["content"] if isinstance(m["content"], str) else str(m["content"])
            if contents and contents[-1]["role"] == role:  # Gemini wants alternating turns
                contents[-1]["parts"][0]["text"] += "\n\n" + text
            else:
                contents.append({"role": role, "parts": [{"text": text}]})
        return {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.3, "topP": 0.9, "maxOutputTokens": 600},
        }

    def _headers(self) -> dict:
        return {"x-goog-api-key": self._key, "content-type": "application/json"}

    @staticmethod
    def _error(r) -> RuntimeError:
        try:
            msg = r.json().get("error", {}).get("message", "")[:160]
        except Exception:  # noqa: BLE001
            msg = r.text[:160]
        return RuntimeError(f"gemini HTTP {r.status_code}: {msg}")

    @staticmethod
    def _text(j: dict) -> str:
        out = []
        for c in j.get("candidates") or []:
            for p in (c.get("content") or {}).get("parts") or []:
                if p.get("text") and not p.get("thought"):
                    out.append(p["text"])
        return "".join(out)

    def complete(self, system: str, messages: list[dict], tools: list[dict] | None = None,
                 tool_results: dict | None = None, on_progress=None) -> LLMResponse:
        import httpx

        body = self._body(system, messages)
        if on_progress is not None:
            return self._complete_streaming(body, on_progress)
        r = httpx.post(f"{self._base}/models/{self._model}:generateContent", json=body,
                       headers=self._headers(), timeout=self.timeout)
        if r.status_code != 200:
            raise self._error(r)
        j = r.json()
        u = j.get("usageMetadata") or {}
        return LLMResponse(text=self._text(j).strip(),
                           usage={"input_tokens": u.get("promptTokenCount", 0),
                                  "output_tokens": u.get("candidatesTokenCount", 0)})

    def _complete_streaming(self, body: dict, on_progress) -> LLMResponse:
        import time

        import httpx

        parts: list[str] = []
        usage: dict = {}
        last = 0.0
        on_progress("prompt", 0)
        url = f"{self._base}/models/{self._model}:streamGenerateContent?alt=sse"
        with httpx.stream("POST", url, json=body, headers=self._headers(), timeout=self.timeout) as r:
            if r.status_code != 200:
                r.read()
                raise self._error(r)
            for line in r.iter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    j = json.loads(line[5:].strip())
                except ValueError:
                    continue
                piece = self._text(j)
                usage = j.get("usageMetadata") or usage
                if piece:
                    parts.append(piece)
                    now = time.monotonic()
                    if len(parts) == 1 or now - last > 0.25:
                        last = now
                        tokens = usage.get("candidatesTokenCount") or len("".join(parts)) // 4
                        on_progress("writing", tokens)
        return LLMResponse(text="".join(parts).strip(),
                           usage={"input_tokens": usage.get("promptTokenCount", 0),
                                  "output_tokens": usage.get("candidatesTokenCount", 0)})


def chat_model() -> Any:
    from shared import byok

    # A visitor's own key (this request only) beats everything else.
    key = byok.current()
    if key:
        return GeminiChatModel(SETTINGS.gemini_chat_model, key, visitor_key=True)
    # Gemini is only used when asked for explicitly, so tests and local runs
    # never spend the free-tier quota by accident.
    if SETTINGS.chat_provider == "gemini" and SETTINGS.gemini_key:
        return GeminiChatModel(SETTINGS.gemini_chat_model, SETTINGS.gemini_key)
    if SETTINGS.chat_enabled():
        return AnthropicChatModel(SETTINGS.chat_model)
    if SETTINGS.chat_provider in ("auto", "ollama"):
        m = resolve_ollama_model()
        if m:
            return OllamaChatModel(m)
    return StubChatModel()


def describe_chat_model() -> dict:
    m = chat_model()
    return {"provider": m.provider, "model": getattr(m, "model", "")}


def helper_model() -> Any:
    # The helper (rewrite/multi-query/verify) uses the same client type.
    return chat_model()
