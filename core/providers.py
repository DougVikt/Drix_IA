"""Provider abstraction for Drix.

Supports:

* ``local``       -- bundled Ollama engine (``ia_system/engine/ollama.exe``)
* ``ollama``      -- Ollama running on another host (LAN / remote)
* ``openai``      -- api.openai.com
* ``anthropic``   -- api.anthropic.com
* ``compatible``  -- any OpenAI-compatible endpoint (Groq, Together,
                     OpenRouter, LM Studio, vLLM, llama.cpp server, ...)

All transports speak the same canonical message format::

    {"role": "system",    "content": str}
    {"role": "user",      "content": str}
    {"role": "assistant", "content": str, "tool_calls": [Call]}
    {"role": "tool",      "tool_call_id": str, "name": str, "content": str}

where ``Call`` is ``{"id", "name", "arguments"}``.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from . import logs, secrets


def _env_key_for_provider(provider: str) -> str:
    p = str(provider or "").strip().upper().replace("-", "_")
    return f"DRIX_{p}_API_KEY"

DEFAULT_BASE_URLS = {
    "local": "http://127.0.0.1:11434",
    "ollama": "http://127.0.0.1:11434",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "compatible": "",
}

DEFAULT_MODELS = {
    "openai": "gpt-4o",
    "anthropic": "claude-sonnet-4-5",
}

PROVIDER_INFO = [
    {
        "id": "local",
        "label": "Local (motor Ollama portátil)",
        "needs_key": False,
        "needs_base_url": False,
        "supports_tools": True,
        "supports_stream": True,
    },
    {
        "id": "ollama",
        "label": "Ollama remoto / LAN",
        "needs_key": False,
        "needs_base_url": True,
        "supports_tools": True,
        "supports_stream": True,
    },
    {
        "id": "openai",
        "label": "OpenAI",
        "needs_key": True,
        "needs_base_url": False,
        "supports_tools": True,
        "supports_stream": True,
    },
    {
        "id": "anthropic",
        "label": "Anthropic (Claude)",
        "needs_key": True,
        "needs_base_url": False,
        "supports_tools": True,
        "supports_stream": True,
    },
    {
        "id": "compatible",
        "label": "OpenAI-compatível (Groq, OpenRouter, LM Studio, vLLM...)",
        "needs_key": True,
        "needs_base_url": True,
        "supports_tools": True,
        "supports_stream": True,
    },
]

_PROVIDER_IDS = {p["id"] for p in PROVIDER_INFO}


class ProviderError(RuntimeError):
    """Raised when a provider call fails."""


@dataclass
class Resolved:
    provider: str
    model: str
    base_url: str
    api_key: str
    temperature: float = 0.7
    max_tokens: int = 1024
    timeout: float = 120.0
    fallback_local: bool = True
    params: dict = field(default_factory=dict)
    keep_alive: str | int = "30m"

    @property
    def supports_tools(self) -> bool:
        return self.provider in {"local", "ollama", "openai", "anthropic", "compatible"}

    @property
    def is_local(self) -> bool:
        return self.provider == "local"


# ─── Config resolution ───────────────────────────────────────────

def _config_dict(cfg=None) -> dict:
    if cfg is not None:
        return cfg
    try:
        from .main import config as _config
        return _config.raw()
    except Exception:
        return {}


def secret_name(provider: str) -> str:
    return f"provider:{provider}"


def resolve(cfg=None) -> Resolved:
    cfg = _config_dict(cfg)
    op = (cfg.get("operation") or {})
    brain = (cfg.get("brain") or {})
    engine = (cfg.get("engine") or {})

    provider = str(op.get("provider") or "").strip().lower()
    if not provider:
        legacy_mode = str(op.get("mode") or "local").strip().lower()
        provider = "local" if legacy_mode == "local" else "openai"
    if provider not in _PROVIDER_IDS:
        provider = "local"

    base_url = str(op.get("base_url") or "").strip() or DEFAULT_BASE_URLS.get(provider, "")

    if provider in {"local", "ollama"}:
        host = str(engine.get("host") or "").strip()
        if host:
            base_url = host if host.startswith("http") else f"http://{host}"
        if provider == "local" and not str(op.get("base_url") or "").strip():
            base_url = f"http://127.0.0.1:{int(engine.get('port') or 11434)}"
        local_model = str(brain.get("local_model") or "").strip()
        explicit = str(op.get("model") or "").strip()
        if provider == "local":
            model = local_model or explicit
        else:
            model = explicit or local_model
    else:
        model = str(op.get("model") or "").strip() or DEFAULT_MODELS.get(provider, "")

    # Priority: env var > secrets store (hidden/protected) > legacy config
    env_key = os.environ.get(_env_key_for_provider(provider), "").strip()
    if not env_key and provider == "openai":
        env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not env_key and provider == "anthropic":
        env_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    api_key = env_key or secrets.get_secret(secret_name(provider))
    if not api_key:
        legacy = op.get("api_key")
        if secrets.is_real_secret(legacy):
            api_key = str(legacy).strip()

    try:
        temperature = float(op.get("temperature", 0.7))
    except (TypeError, ValueError):
        temperature = 0.7
    try:
        max_tokens = int(op.get("max_tokens", 1024))
    except (TypeError, ValueError):
        max_tokens = 1024
    try:
        timeout = float(op.get("timeout", 120))
    except (TypeError, ValueError):
        timeout = 120.0

    # Keep the local model loaded between turns.  Without this Ollama evicts
    # it after 5 minutes, and the next message pays a 40-90 s cold load from
    # the external HD.  ``-1`` means "until the engine stops".
    keep_alive: str | int = op.get("keep_alive", engine.get("keep_alive", "30m"))
    if isinstance(keep_alive, str):
        keep_alive = keep_alive.strip() or "30m"
        if keep_alive.lstrip("-").isdigit():
            keep_alive = int(keep_alive)

    return Resolved(
        provider=provider,
        model=model,
        base_url=base_url.rstrip("/"),
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        fallback_local=bool(op.get("fallback_local", True)),
        params=dict(brain.get("model_params") or {}),
        keep_alive=keep_alive,
    )


def describe(cfg=None) -> dict:
    r = resolve(cfg)
    return {
        "provider": r.provider,
        "model": r.model,
        "base_url": r.base_url,
        "has_key": bool(r.api_key),
        "key_hint": secrets.mask(r.api_key),
        "temperature": r.temperature,
        "max_tokens": r.max_tokens,
        "timeout": r.timeout,
        "keep_alive": r.keep_alive,
        "fallback_local": r.fallback_local,
        "encryption": secrets.encryption_mode(),
    }


# ─── Helpers ─────────────────────────────────────────────────────

async def _aiter_blocking(factory) -> AsyncIterator[Any]:
    """Turn a blocking iterator factory into an async iterator."""
    q: queue.Queue = queue.Queue()
    stop = object()

    def _run():
        try:
            for item in factory():
                q.put(item)
        except Exception as exc:  # noqa: BLE001 - forwarded to the consumer
            q.put(exc)
        finally:
            q.put(stop)

    threading.Thread(target=_run, daemon=True).start()
    while True:
        item = await asyncio.to_thread(q.get)
        if item is stop:
            break
        if isinstance(item, Exception):
            raise item
        yield item


def _join_url(base: str, path: str) -> str:
    base = (base or "").rstrip("/")
    if not base:
        raise ProviderError("base_url não configurada para este provider")
    if base.endswith("/chat/completions") or base.endswith("/messages"):
        return base
    return f"{base}{path}"


def _http_error(resp: httpx.Response) -> ProviderError:
    try:
        payload = resp.json()
    except Exception:
        payload = resp.text[:400]
    return ProviderError(f"HTTP {resp.status_code}: {payload}")


# ─── Message conversion ──────────────────────────────────────────

def _openai_messages(messages: list[dict]) -> list[dict]:
    out = []
    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": msg.get("content") or None,
                "tool_calls": [
                    {
                        "id": call["id"],
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False),
                        },
                    }
                    for call in msg["tool_calls"]
                ],
            })
        elif role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": msg.get("tool_call_id", ""),
                "content": str(msg.get("content") or ""),
            })
        else:
            out.append({"role": role, "content": msg.get("content") or ""})
    return out


def _openai_tools(tools: list[dict] | None) -> list[dict] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters") or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


def _anthropic_payload(r: Resolved, messages: list[dict], tools: list[dict] | None) -> dict:
    system_parts = [m.get("content", "") for m in messages if m.get("role") == "system"]
    convo: list[dict] = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            continue
        if role == "tool":
            block = {
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id", ""),
                    "content": str(msg.get("content") or ""),
                }],
            }
            convo.append(block)
        elif role == "assistant":
            blocks: list[dict] = []
            if msg.get("content"):
                blocks.append({"type": "text", "text": msg["content"]})
            for call in msg.get("tool_calls") or []:
                blocks.append({
                    "type": "tool_use",
                    "id": call["id"],
                    "name": call["name"],
                    "input": call.get("arguments") or {},
                })
            if not blocks:
                blocks = [{"type": "text", "text": ""}]
            convo.append({"role": "assistant", "content": blocks})
        else:
            text = str(msg.get("content") or "")
            if convo and convo[-1]["role"] == "user" and isinstance(convo[-1].get("content"), list):
                if all(b.get("type") != "tool_result" for b in convo[-1]["content"]):
                    convo[-1]["content"].append({"type": "text", "text": text})
                    continue
            convo.append({"role": "user", "content": [{"type": "text", "text": text}]})

    # Merge consecutive messages with the same role (Anthropic requires alternation).
    merged: list[dict] = []
    for msg in convo:
        if merged and merged[-1]["role"] == msg["role"]:
            merged[-1]["content"].extend(msg["content"])
        else:
            merged.append(msg)
    if merged and merged[0]["role"] != "user":
        merged.insert(0, {"role": "user", "content": [{"type": "text", "text": "(início)"}]})

    payload: dict = {
        "model": r.model,
        "max_tokens": r.max_tokens,
        "messages": merged,
        "temperature": r.temperature,
    }
    if system_parts:
        payload["system"] = "\n\n".join(p for p in system_parts if p)
    if tools:
        payload["tools"] = [
            {
                "name": t["name"],
                "description": t.get("description", ""),
                "input_schema": t.get("parameters") or {"type": "object", "properties": {}},
            }
            for t in tools
        ]
    return payload


def _ollama_messages(messages: list[dict]) -> list[dict]:
    out = []
    for msg in messages:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            out.append({
                "role": "assistant",
                "content": msg.get("content") or "",
                "tool_calls": [
                    {"function": {"name": c["name"], "arguments": c.get("arguments") or {}}}
                    for c in msg["tool_calls"]
                ],
            })
        elif role == "tool":
            out.append({
                "role": "tool",
                "tool_name": msg.get("name", ""),
                "content": str(msg.get("content") or ""),
            })
        else:
            out.append({"role": role, "content": msg.get("content") or ""})
    return out


# ─── Ollama transport ────────────────────────────────────────────

def _ollama_client(r: Resolved):
    try:
        import ollama
    except Exception as exc:  # pragma: no cover
        raise ProviderError(f"pacote ollama não instalado: {exc}") from exc
    host = r.base_url
    if host.endswith("/v1"):
        host = host[:-3]
    return ollama.Client(host=host or DEFAULT_BASE_URLS["local"])


def _ollama_options(r: Resolved) -> dict:
    params = r.params or {}
    options: dict = {}
    if "ctx" in params:
        options["num_ctx"] = params["ctx"]
    if "threads" in params:
        options["num_thread"] = params["threads"]
    options.setdefault("temperature", r.temperature)
    options.setdefault("num_predict", r.max_tokens)
    # Small local models often continue past the answer and invent a new
    # "---" section with another question.  Stop at that separator; without
    # this the reply can be 3-4x longer (and slower) than requested.
    options.setdefault("stop", ["\n\n---"])
    return options


def _ollama_calls(message: dict) -> list[dict]:
    calls = []
    for idx, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"_raw": args}
        calls.append({
            "id": call.get("id") or f"call_{idx}",
            "name": fn.get("name", ""),
            "arguments": args or {},
        })
    return calls


async def _ollama_chat(r: Resolved, messages: list[dict], tools=None) -> dict:
    client = _ollama_client(r)

    def _call():
        return client.chat(
            model=r.model,
            messages=_ollama_messages(messages),
            options=_ollama_options(r),
            tools=_openai_tools(tools) if tools else None,
            keep_alive=r.keep_alive,
        )

    try:
        resp = await asyncio.to_thread(_call)
    except Exception as exc:
        raise ProviderError(f"Ollama: {exc}") from exc
    message = resp.get("message") or {}
    return {"content": message.get("content") or "", "tool_calls": _ollama_calls(message)}


async def _ollama_stream(r: Resolved, messages: list[dict]) -> AsyncIterator[str]:
    client = _ollama_client(r)

    def _factory():
        stream = client.chat(
            model=r.model,
            messages=_ollama_messages(messages),
            options=_ollama_options(r),
            stream=True,
            keep_alive=r.keep_alive,
        )
        for chunk in stream:
            text = (chunk.get("message") or {}).get("content") or ""
            if text:
                yield text

    try:
        async for token in _aiter_blocking(_factory):
            yield token
    except ProviderError:
        raise
    except Exception as exc:
        raise ProviderError(f"Ollama: {exc}") from exc


# ─── OpenAI-compatible transport ─────────────────────────────────

def _openai_headers(r: Resolved) -> dict:
    headers = {"Content-Type": "application/json"}
    if r.api_key:
        headers["Authorization"] = f"Bearer {r.api_key}"
    return headers


def _openai_payload(r: Resolved, messages: list[dict], tools, stream: bool) -> dict:
    payload: dict = {
        "model": r.model,
        "messages": _openai_messages(messages),
        "temperature": r.temperature,
        "max_tokens": r.max_tokens,
        "stream": stream,
    }
    if r.provider == "openai" and r.model.startswith(("o1", "o3", "o4")):
        payload.pop("temperature", None)
        payload.pop("max_tokens", None)
        payload["max_completion_tokens"] = r.max_tokens
    converted = _openai_tools(tools)
    if converted:
        payload["tools"] = converted
        payload["tool_choice"] = "auto"
    return payload


def _parse_openai_calls(message: dict) -> list[dict]:
    calls = []
    for idx, call in enumerate(message.get("tool_calls") or []):
        fn = call.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except Exception:
                args = {"_raw": args}
        calls.append({
            "id": call.get("id") or f"call_{idx}",
            "name": fn.get("name", ""),
            "arguments": args or {},
        })
    return calls


async def _openai_chat(r: Resolved, messages: list[dict], tools=None) -> dict:
    url = _join_url(r.base_url, "/chat/completions")
    payload = _openai_payload(r, messages, tools, stream=False)
    timeout = httpx.Timeout(r.timeout, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=_openai_headers(r))
        if resp.status_code >= 400:
            raise _http_error(resp)
        data = resp.json()
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise ProviderError(f"resposta inesperada do provider: {str(data)[:300]}") from exc
    return {"content": message.get("content") or "", "tool_calls": _parse_openai_calls(message)}


async def _openai_stream(r: Resolved, messages: list[dict]) -> AsyncIterator[str]:
    url = _join_url(r.base_url, "/chat/completions")
    payload = _openai_payload(r, messages, None, stream=True)
    timeout = httpx.Timeout(r.timeout, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", url, json=payload, headers=_openai_headers(r)) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise ProviderError(f"HTTP {resp.status_code}: {body[:400]!r}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                if chunk == "[DONE]":
                    break
                try:
                    data = json.loads(chunk)
                except Exception:
                    continue
                choices = data.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                text = delta.get("content")
                if text:
                    yield text


# ─── Anthropic transport ─────────────────────────────────────────

def _anthropic_headers(r: Resolved) -> dict:
    return {
        "Content-Type": "application/json",
        "x-api-key": r.api_key,
        "anthropic-version": "2023-06-01",
    }


def _anthropic_url(r: Resolved) -> str:
    base = r.base_url.rstrip("/")
    if base.endswith("/messages"):
        return base
    return f"{base}/messages"


def _parse_anthropic_blocks(data: dict) -> dict:
    text_parts = []
    calls = []
    for block in data.get("content") or []:
        if block.get("type") == "text":
            text_parts.append(block.get("text") or "")
        elif block.get("type") == "tool_use":
            calls.append({
                "id": block.get("id") or "",
                "name": block.get("name") or "",
                "arguments": block.get("input") or {},
            })
    return {"content": "".join(text_parts), "tool_calls": calls}


async def _anthropic_chat(r: Resolved, messages: list[dict], tools=None) -> dict:
    payload = _anthropic_payload(r, messages, tools)
    timeout = httpx.Timeout(r.timeout, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(_anthropic_url(r), json=payload, headers=_anthropic_headers(r))
        if resp.status_code >= 400:
            raise _http_error(resp)
        data = resp.json()
    return _parse_anthropic_blocks(data)


async def _anthropic_stream(r: Resolved, messages: list[dict]) -> AsyncIterator[str]:
    payload = _anthropic_payload(r, messages, None)
    payload["stream"] = True
    timeout = httpx.Timeout(r.timeout, connect=15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream("POST", _anthropic_url(r), json=payload,
                                 headers=_anthropic_headers(r)) as resp:
            if resp.status_code >= 400:
                body = await resp.aread()
                raise ProviderError(f"HTTP {resp.status_code}: {body[:400]!r}")
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                chunk = line[5:].strip()
                try:
                    data = json.loads(chunk)
                except Exception:
                    continue
                if data.get("type") == "content_block_delta":
                    delta = data.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        yield delta["text"]
                elif data.get("type") == "message_stop":
                    break


# ─── Public API ──────────────────────────────────────────────────

def _dispatch_chat(r: Resolved, messages, tools):
    if r.provider in {"local", "ollama"}:
        return _ollama_chat(r, messages, tools)
    if r.provider == "anthropic":
        return _anthropic_chat(r, messages, tools)
    return _openai_chat(r, messages, tools)


def _dispatch_stream(r: Resolved, messages):
    if r.provider in {"local", "ollama"}:
        return _ollama_stream(r, messages)
    if r.provider == "anthropic":
        return _anthropic_stream(r, messages)
    return _openai_stream(r, messages)


def _local_fallback(r: Resolved) -> Resolved:
    cfg = _config_dict()
    brain = cfg.get("brain") or {}
    engine = cfg.get("engine") or {}
    port = int(engine.get("port") or 11434)
    return Resolved(
        provider="local",
        model=str(brain.get("local_model") or r.model),
        base_url=f"http://127.0.0.1:{port}",
        api_key="",
        temperature=r.temperature,
        max_tokens=r.max_tokens,
        timeout=r.timeout,
        fallback_local=False,
        params=dict(brain.get("model_params") or {}),
        keep_alive=r.keep_alive,
    )


async def chat(messages: list[dict], tools: list[dict] | None = None, cfg=None) -> dict:
    """Non-streaming completion. Returns ``{"content", "tool_calls"}``."""
    r = resolve(cfg)
    try:
        return await _dispatch_chat(r, messages, tools)
    except Exception as exc:
        if r.provider != "local" and r.fallback_local:
            logs.warn(f"Provider {r.provider} failed ({exc}); falling back to local engine")
            try:
                return await _ollama_chat(_local_fallback(r), messages, tools)
            except Exception as local_exc:
                raise ProviderError(f"{exc} | fallback local: {local_exc}") from local_exc
        raise ProviderError(str(exc)) from exc


async def stream(messages: list[dict], cfg=None) -> AsyncIterator[str]:
    """Streaming completion. Yields text tokens."""
    r = resolve(cfg)
    produced = False
    try:
        async for token in _dispatch_stream(r, messages):
            produced = True
            yield token
        return
    except Exception as exc:
        if produced or r.provider == "local" or not r.fallback_local:
            raise ProviderError(str(exc)) from exc
        logs.warn(f"Provider {r.provider} stream failed ({exc}); falling back to local engine")
    async for token in _ollama_stream(_local_fallback(r), messages):
        yield token


async def complete(messages: list[dict], cfg=None) -> str:
    result = await chat(messages, tools=None, cfg=cfg)
    return result.get("content") or ""


async def test_connection(cfg=None) -> dict:
    import time

    r = resolve(cfg)
    started = time.time()
    result = await chat([
        {"role": "system", "content": "Reply with the single word: ok"},
        {"role": "user", "content": "ping"},
    ], tools=None, cfg=cfg)
    return {
        "ok": True,
        "provider": r.provider,
        "model": r.model,
        "latency_ms": int((time.time() - started) * 1000),
        "reply": (result.get("content") or "")[:200],
    }


def provider_catalog() -> list[dict]:
    return [dict(p) for p in PROVIDER_INFO]
