"""Tool-calling agent loop.

The loop is provider agnostic: it uses the canonical message format from
``core.providers`` and yields structured events so the API can stream tool
activity to the UI.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from . import logs, providers, tools


def _chunk(text: str, size: int = 24) -> list[str]:
    if not text:
        return []
    words = text.split(" ")
    out: list[str] = []
    buffer = ""
    for index, word in enumerate(words):
        piece = word if index == 0 else " " + word
        if len(buffer) + len(piece) > size and buffer:
            out.append(buffer)
            buffer = piece
        else:
            buffer += piece
    if buffer:
        out.append(buffer)
    return out


async def run(query: str, conv_mgr=None, *, workspace: str = "default",
              approvals=frozenset(), allowed_tools: list[str] | None = None,
              cfg: dict | None = None, use_tools: bool = True,
              system_extra: str = "", max_steps: int | None = None,
              depth: int = 0) -> AsyncIterator[dict]:
    """Run the agent and yield events.

    Event types: ``token``, ``tool_call``, ``tool_result``, ``approval_required``,
    ``final``, ``error``.
    """
    from .main import _build_prompt, _save_memory, lang

    # Register optional tool packs (MCP servers, subagents) on first use.
    try:
        from . import mcp as _mcp  # noqa: F401
    except Exception:
        pass
    try:
        from . import subagents as _subagents  # noqa: F401
    except Exception:
        pass

    cfg = cfg if cfg is not None else _snapshot_cfg()
    prompt = await _build_prompt(query, conv_mgr)

    tools_cfg = cfg.get("tools") or {}
    if max_steps is None:
        try:
            max_steps = int(tools_cfg.get("max_steps", 6))
        except (TypeError, ValueError):
            max_steps = 6

    enabled = bool(tools_cfg.get("enabled", True)) and use_tools
    ctx = tools.ToolContext(cfg=cfg, workspace=workspace,
                            approvals=frozenset(approvals), extra={"_depth": depth})

    system = lang.get("system_prompt")
    if system_extra:
        system = f"{system}\n\n{system_extra}"

    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    final_text = ""
    tool_log: list[dict] = []
    provider_tools = tools.schemas(allowed_tools) if enabled else None

    for step in range(max(1, max_steps)):
        try:
            result = await providers.chat(messages, tools=provider_tools, cfg=cfg)
        except Exception as exc:
            message = str(exc)
            if provider_tools and "tool" in message.lower():
                logs.warn(f"Provider rejected tools, retrying without them: {exc}")
                provider_tools = None
                result = await providers.chat(messages, tools=None, cfg=cfg)
            else:
                logs.error(f"Agent provider error: {exc}")
                yield {"type": "error", "message": message}
                return

        calls = result.get("tool_calls") or []
        content = result.get("content") or ""

        if not calls:
            final_text = content
            break

        messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": calls,
        })

        for call in calls:
            name = call.get("name") or ""
            arguments = call.get("arguments") or {}
            yield {"type": "tool_call", "name": name, "arguments": arguments,
                   "step": step + 1, "id": call.get("id")}

            if allowed_tools is not None and name not in allowed_tools:
                output = f"ERROR: ferramenta '{name}' não permitida neste contexto"
            else:
                try:
                    output = await tools.execute_async(name, arguments, ctx)
                except tools.ApprovalRequired as exc:
                    payload = exc.to_dict()
                    payload["type"] = "approval_required"
                    yield payload
                    return

            tool_log.append({"name": name, "arguments": arguments, "result": output[:500]})
            yield {"type": "tool_result", "name": name, "result": output}
            messages.append({
                "role": "tool",
                "tool_call_id": call.get("id") or "",
                "name": name,
                "content": output,
            })
    else:
        final_text = content or ""

    if not final_text:
        final_text = "Não consegui concluir a tarefa com as ferramentas disponíveis."

    for piece in _chunk(final_text):
        yield {"type": "token", "text": piece}

    if conv_mgr:
        conv_mgr.add_message("user", query)
        conv_mgr.add_message("assistant", final_text)
    try:
        import asyncio
        asyncio.create_task(_save_memory(query, final_text))
    except Exception:
        pass

    yield {"type": "final", "text": final_text, "tools": tool_log}


def _snapshot_cfg() -> dict:
    try:
        from .main import config
        return config.raw()
    except Exception:
        return {}


async def run_to_text(query: str, conv_mgr=None, **kwargs) -> str:
    text = ""
    async for event in run(query, conv_mgr, **kwargs):
        if event.get("type") == "final":
            text = event.get("text") or text
        elif event.get("type") == "error":
            return f"ERROR: {event.get('message')}"
        elif event.get("type") == "approval_required":
            return json.dumps(event, ensure_ascii=False)
    return text
