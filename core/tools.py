"""Tool registry with explicit permissions.

Every tool is gated by ``config.yaml``::

    tools:
      enabled: true
      default_permission: allow    # allow | ask | deny
      permissions:
        write_file: ask
        run_shell: deny

``ask`` makes the agent pause and return an approval token to the caller; the
same call can then be retried with that token to execute it. Decisions the user
chooses to remember live in the host's local cache (see ``core.permissions``),
not in ``config.yaml``; explicit rules in the config always win.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import logs, permissions, snapshots
from . import platform_paths

ROOT = Path(__file__).resolve().parent.parent

_SKIP_DIRS = {"__pycache__", ".git", ".venv", "node_modules", ".cache",
              "ia_system", "poetry_cache", ".chainlit"}


class ApprovalRequired(Exception):
    """Raised when a tool needs explicit user confirmation."""

    def __init__(self, tool: str, arguments: dict, token: str, preview: str = ""):
        super().__init__(f"approval required for {tool}")
        self.tool = tool
        self.arguments = arguments
        self.token = token
        self.preview = preview

    def to_dict(self) -> dict:
        return {
            "status": "approval_required",
            "tool": self.tool,
            "arguments": self.arguments,
            "approval_token": self.token,
            "preview": self.preview,
        }


class ToolError(RuntimeError):
    pass


@dataclass
class ToolContext:
    cfg: dict
    workspace: str = "default"
    approvals: frozenset[str] = frozenset()
    extra: dict = field(default_factory=dict)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[dict, ToolContext], str]
    danger: str = "read"  # read | write | network | execute


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool) -> Tool:
    _REGISTRY[tool.name] = tool
    return tool


def get(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def names() -> list[str]:
    return sorted(_REGISTRY)


def schemas(allowed: list[str] | None = None) -> list[dict]:
    out = []
    for name in sorted(_REGISTRY):
        if allowed is not None and name not in allowed:
            continue
        tool = _REGISTRY[name]
        out.append({
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        })
    return out


def permission_for(name: str, cfg: dict) -> str:
    tools_cfg = cfg.get("tools") or {}
    perms = tools_cfg.get("permissions") or {}
    return str(perms.get(name, tools_cfg.get("default_permission", "allow"))).lower()


def approval_token(name: str, arguments: dict, workspace: str) -> str:
    payload = json.dumps(
        {"tool": name, "args": arguments, "ws": workspace},
        sort_keys=True, ensure_ascii=False, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _preview(name: str, arguments: dict) -> str:
    if name in {"write_file"}:
        path = arguments.get("path", "?")
        content = str(arguments.get("content", ""))
        return f"gravar {len(content)} bytes em {path}"
    if name == "run_shell":
        return f"executar: {arguments.get('command', '')}"
    if name == "maps_download":
        return f"baixar mapa de {arguments.get('url', '?')}"
    if name == "maps_extract":
        preset = arguments.get("preset") or "recorte personalizado"
        return f"extrair mapa ({preset})"
    if name == "maps_delete":
        return f"apagar mapa {arguments.get('name') or arguments.get('map_id') or '?'}"
    return f"{name} {json.dumps(arguments, ensure_ascii=False)[:300]}"


def _guard(name: str, arguments: dict | None, ctx: ToolContext):
    """Return ``(tool, arguments)`` on success or ``(None, error_message)``."""
    arguments = arguments or {}
    tool = _REGISTRY.get(name)
    if not tool:
        return None, f"ERROR: ferramenta desconhecida '{name}'"

    cfg = ctx.cfg or {}
    if not (cfg.get("tools") or {}).get("enabled", True):
        return None, "ERROR: ferramentas desativadas em config.yaml (tools.enabled=false)"

    permission = permission_for(name, cfg)
    if permission == "deny":
        logs.warn(f"Tool denied: {name}")
        return None, (f"ERROR: ferramenta '{name}' bloqueada por permissão "
                      f"(tools.permissions.{name}=deny)")

    if permission == "ask":
        cached = None
        try:
            cached = permissions.decision_for(name, arguments)
        except Exception as exc:  # cache never blocks tool execution
            logs.warn(f"Permission cache read failed: {exc}")
        if cached == "allow":
            return tool, arguments
        if cached == "deny":
            logs.warn(f"Tool denied by local cache: {name}")
            return None, (f"ERROR: ferramenta '{name}' negada por uma decisão "
                          "lembrada no cache local de permissões")
        token = approval_token(name, arguments, ctx.workspace)
        if token not in (ctx.approvals or frozenset()):
            raise ApprovalRequired(name, arguments, token, _preview(name, arguments))

    return tool, arguments


def _finish(name: str, result, started: float) -> str:
    elapsed = int((time.time() - started) * 1000)
    logs.info(f"Tool {name} ({elapsed} ms) -> {str(result)[:120]!r}")
    return str(result)


def _run_handler(tool: Tool, arguments: dict, ctx: ToolContext) -> str:
    try:
        return tool.handler(arguments, ctx)
    except ToolError as exc:
        return f"ERROR: {exc}"
    except Exception as exc:  # noqa: BLE001 - surfaced to the model
        logs.warn(f"Tool {tool.name} failed: {exc}")
        return f"ERROR: {exc}"


def execute(name: str, arguments: dict | None, ctx: ToolContext) -> str:
    """Synchronous execution (returns an ERROR string for async tools)."""
    tool, payload = _guard(name, arguments, ctx)
    if tool is None:
        return payload
    started = time.time()
    result = _run_handler(tool, payload, ctx)
    if inspect.isawaitable(result):
        return f"ERROR: ferramenta '{name}' é assíncrona; use execute_async"
    return _finish(name, result, started)


async def execute_async(name: str, arguments: dict | None, ctx: ToolContext) -> str:
    """Async-aware execution used by the agent loop."""
    tool, payload = _guard(name, arguments, ctx)
    if tool is None:
        return payload
    started = time.time()
    result = _run_handler(tool, payload, ctx)
    if inspect.isawaitable(result):
        try:
            result = await result
        except ToolError as exc:
            result = f"ERROR: {exc}"
        except Exception as exc:  # noqa: BLE001
            logs.warn(f"Tool {name} failed: {exc}")
            result = f"ERROR: {exc}"
    return _finish(name, result, started)


# ─── Path helpers ────────────────────────────────────────────────

def _resolve(path_str: str) -> Path:
    return platform_paths.expand_path(path_str or ".", base=ROOT).resolve()


def _security(cfg: dict):
    from .main import SecurityBridge

    return SecurityBridge(cfg)


def _check(path: Path, mode: str, cfg: dict) -> str | None:
    if _security(cfg).can_access(str(path), mode):
        return None
    return f"acesso negado ({mode}) a {path}"


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except Exception:
        return str(path)


def _decode(data: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except Exception:
            continue
    return data.decode("utf-8", "replace")


# ─── Handlers ────────────────────────────────────────────────────

def _system_info(args: dict, ctx: ToolContext) -> str:
    from . import hardware, providers

    hw = hardware.analyze()
    info = {
        "ram_gb": hw.get("ram_gb"),
        "cpu_cores": hw.get("cpu_cores"),
        "selected_model": hw.get("selected_model"),
        "provider": providers.describe(ctx.cfg),
        "workspace": ctx.workspace,
        "host_write": (ctx.cfg.get("security") or {}).get("allow_host_write", False),
        "tools": names(),
    }
    try:
        from api import engine
        info["engine"] = engine.status()
    except Exception:
        pass
    return json.dumps(info, indent=2, ensure_ascii=False, default=str)


def _list_directory(args: dict, ctx: ToolContext) -> str:
    path = _resolve(args.get("path", "."))
    denied = _check(path, "read", ctx.cfg)
    if denied:
        raise ToolError(denied)
    if not path.is_dir():
        raise ToolError(f"diretório não encontrado: {path}")
    try:
        limit = min(int(args.get("max_entries", 200)), 1000)
    except (TypeError, ValueError):
        limit = 200

    entries = []
    for item in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if item.name in _SKIP_DIRS:
            continue
        try:
            size = item.stat().st_size if item.is_file() else None
        except Exception:
            size = None
        entries.append({
            "name": item.name,
            "type": "dir" if item.is_dir() else "file",
            "size": size,
        })
        if len(entries) >= limit:
            break
    return json.dumps({"path": _rel(path), "entries": entries}, ensure_ascii=False)


def _read_file(args: dict, ctx: ToolContext) -> str:
    path = _resolve(args.get("path", ""))
    denied = _check(path, "read", ctx.cfg)
    if denied:
        raise ToolError(denied)
    if not path.is_file():
        raise ToolError(f"arquivo não encontrado: {path}")

    try:
        max_bytes = min(int(args.get("max_bytes", 60000)), 400000)
    except (TypeError, ValueError):
        max_bytes = 60000

    raw = path.read_bytes()
    truncated = len(raw) > max_bytes
    text = _decode(raw[:max_bytes])

    start = args.get("start_line")
    end = args.get("end_line")
    if start or end:
        lines = text.splitlines()
        try:
            first = max(0, int(start) - 1) if start else 0
            last = int(end) if end else len(lines)
        except (TypeError, ValueError):
            first, last = 0, len(lines)
        text = "\n".join(lines[first:last])

    header = f"# {_rel(path)} ({len(raw)} bytes"
    header += ", truncado" if truncated else ""
    header += ")\n"
    return header + text


def _search_files(args: dict, ctx: ToolContext) -> str:
    pattern = str(args.get("pattern") or "*").strip()
    if not pattern or len(pattern) > 200:
        raise ToolError("pattern inválido")
    base = _resolve(args.get("path", "."))
    denied = _check(base, "read", ctx.cfg)
    if denied:
        raise ToolError(denied)
    try:
        limit = min(int(args.get("max_results", 100)), 500)
    except (TypeError, ValueError):
        limit = 100

    results = []
    for path in base.rglob(pattern):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        try:
            results.append({
                "path": _rel(path),
                "type": "dir" if path.is_dir() else "file",
                "size": path.stat().st_size if path.is_file() else None,
            })
        except Exception:
            continue
        if len(results) >= limit:
            break
    return json.dumps({"pattern": pattern, "results": results}, ensure_ascii=False)


def _write_file(args: dict, ctx: ToolContext) -> str:
    path = _resolve(args.get("path", ""))
    denied = _check(path, "write", ctx.cfg)
    if denied:
        raise ToolError(denied)
    if not str(args.get("path") or "").strip():
        raise ToolError("path é obrigatório")

    content = str(args.get("content", ""))
    snapshot_info = ""
    if path.exists() and (ctx.cfg.get("snapshots") or {}).get("enabled", True):
        manifest = snapshots.create([path], label=f"antes de write_file: {_rel(path)}")
        if manifest.get("id"):
            snapshot_info = f" (snapshot {manifest['id']})"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"OK: {len(content)} bytes gravados em {_rel(path)}{snapshot_info}"


def _web_search(args: dict, ctx: ToolContext) -> str:
    if not (ctx.cfg.get("network") or {}).get("allow_internet_access", False):
        raise ToolError("acesso à internet desativado (network.allow_internet_access=false)")
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("query é obrigatória")
    from . import web

    try:
        limit = min(int(args.get("max_results", 5)), 10)
    except (TypeError, ValueError):
        limit = 5
    results = web.search(query, max_results=limit) if "max_results" in web.search.__code__.co_varnames \
        else web.search(query)
    return "\n\n".join(results[:limit]) if results else "Nenhum resultado."


def _fetch_url(args: dict, ctx: ToolContext) -> str:
    if not (ctx.cfg.get("network") or {}).get("allow_internet_access", False):
        raise ToolError("acesso à internet desativado (network.allow_internet_access=false)")
    url = str(args.get("url") or "").strip()
    if not url:
        raise ToolError("url é obrigatória")
    from . import web

    web.check_url(url)
    content = web.fetch(url)
    try:
        limit = min(int(args.get("max_chars", 8000)), 40000)
    except (TypeError, ValueError):
        limit = 8000
    if len(content) > limit:
        content = content[:limit] + "\n[truncado]"
    return content


def _memory_search(args: dict, ctx: ToolContext) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ToolError("query é obrigatória")
    from . import memory

    try:
        limit = min(int(args.get("limit", 5)), 20)
    except (TypeError, ValueError):
        limit = 5
    results = memory.search(query, limit=limit)
    return json.dumps({"results": results}, ensure_ascii=False)


def _memory_add(args: dict, ctx: ToolContext) -> str:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ToolError("text é obrigatório")
    from . import memory

    memory.add({"user": text, "assistant": ""})
    return "OK: memória registrada"


def _run_shell(args: dict, ctx: ToolContext) -> str:
    command = str(args.get("command") or "").strip()
    if not command:
        raise ToolError("command é obrigatório")
    if not (ctx.cfg.get("security") or {}).get("allow_host_write", False):
        raise ToolError("execução bloqueada: security.allow_host_write=false")
    try:
        timeout = min(int(args.get("timeout", 30)), 120)
    except (TypeError, ValueError):
        timeout = 30

    result = subprocess.run(
        command, shell=True, cwd=str(ROOT),
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace",
    )
    output = (result.stdout or "") + (("\n[stderr]\n" + result.stderr) if result.stderr else "")
    if len(output) > 20000:
        output = output[:20000] + "\n[truncado]"
    return f"exit={result.returncode}\n{output}".strip()


def _snapshot_list(args: dict, ctx: ToolContext) -> str:
    items = [
        {"id": s["id"], "label": s["label"], "created_at": s["created_at"], "files": len(s["files"])}
        for s in snapshots.list_snapshots(limit=20)
    ]
    return json.dumps({"snapshots": items}, ensure_ascii=False)


def _snapshot_restore(args: dict, ctx: ToolContext) -> str:
    snapshot_id = str(args.get("id") or "").strip()
    if not snapshot_id:
        raise ToolError("id é obrigatório")
    allow_external = bool((ctx.cfg.get("security") or {}).get("allow_host_write", False))
    result = snapshots.restore(snapshot_id, allow_external=allow_external)
    return json.dumps(result, ensure_ascii=False)


# ─── Registration ────────────────────────────────────────────────

register(Tool(
    "system_info",
    "Informações do hardware, modelo/provider ativo, workspace e ferramentas disponíveis.",
    {"type": "object", "properties": {}},
    _system_info,
))

register(Tool(
    "list_directory",
    "Lista arquivos e pastas de um diretório.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Caminho (relativo ao HD por padrão)."},
            "max_entries": {"type": "integer", "description": "Máximo de entradas (padrão 200)."},
        },
    },
    _list_directory,
))

register(Tool(
    "read_file",
    "Lê um arquivo de texto. Use start_line/end_line para trechos grandes.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "max_bytes": {"type": "integer"},
            "start_line": {"type": "integer"},
            "end_line": {"type": "integer"},
        },
        "required": ["path"],
    },
    _read_file,
))

register(Tool(
    "search_files",
    "Busca arquivos por padrão glob (ex.: *.py, config/*.yaml).",
    {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        "required": ["pattern"],
    },
    _search_files,
))

register(Tool(
    "write_file",
    "Grava um arquivo de texto. Cria snapshot do conteúdo anterior automaticamente.",
    {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["path", "content"],
    },
    _write_file,
    danger="write",
))

register(Tool(
    "web_search",
    "Pesquisa na web (DuckDuckGo) e devolve resultados resumidos.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "max_results": {"type": "integer"},
        },
        "required": ["query"],
    },
    _web_search,
    danger="network",
))

register(Tool(
    "fetch_url",
    "Baixa uma página e converte para texto. URLs locais/rede privada são bloqueadas.",
    {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "max_chars": {"type": "integer"},
        },
        "required": ["url"],
    },
    _fetch_url,
    danger="network",
))

register(Tool(
    "memory_search",
    "Busca memórias de longo prazo da Drix.",
    {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer"},
        },
        "required": ["query"],
    },
    _memory_search,
))

register(Tool(
    "memory_add",
    "Guarda uma informação na memória de longo prazo.",
    {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    _memory_add,
    danger="write",
))

register(Tool(
    "run_shell",
    "Executa um comando no shell do sistema. Desativado por padrão.",
    {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer"},
        },
        "required": ["command"],
    },
    _run_shell,
    danger="execute",
))

register(Tool(
    "snapshot_list",
    "Lista snapshots disponíveis para desfazer alterações.",
    {"type": "object", "properties": {}},
    _snapshot_list,
))

register(Tool(
    "snapshot_restore",
    "Restaura os arquivos de um snapshot.",
    {
        "type": "object",
        "properties": {"id": {"type": "string"}},
        "required": ["id"],
    },
    _snapshot_restore,
    danger="write",
))
