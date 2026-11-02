"""Minimal MCP (Model Context Protocol) client over stdio.

No external dependency: MCP stdio messages are newline-delimited JSON-RPC 2.0.
Servers are declared in ``config.yaml``::

    mcp:
      enabled: true
      servers:
        filesystem:
          command: npx
          args: ["-y", "@modelcontextprotocol/server-filesystem", "F:/workspace"]
          env: {}
          enabled: true
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time

from . import logs, tools

PROTOCOL_VERSION = "2024-11-05"


class MCPError(RuntimeError):
    pass


def _flatten(result: dict) -> str:
    parts = []
    for block in result.get("content") or []:
        if isinstance(block, str):
            parts.append(block)
            continue
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text") or "")
        elif kind == "resource":
            resource = block.get("resource") or {}
            parts.append(resource.get("text") or resource.get("uri") or json.dumps(resource))
        else:
            parts.append(json.dumps(block, ensure_ascii=False))
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        text = json.dumps(result, ensure_ascii=False)
    if result.get("isError"):
        text = "ERROR: " + text
    return text


class MCPClient:
    def __init__(self, name: str, command: str, args=None, env=None, cwd=None, timeout: float = 30.0):
        self.name = name
        self.command = str(command)
        self.args = [str(a) for a in (args or [])]
        self.env = dict(env or {})
        self.cwd = cwd
        self.timeout = float(timeout)
        self.server_info: dict = {}
        self._proc: subprocess.Popen | None = None
        self._queue: queue.Queue = queue.Queue()
        self._lock = threading.RLock()
        self._next_id = 0
        self._tools: list[dict] | None = None

    # ─── lifecycle ───────────────────────────────────────────

    def start(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            return
        env = os.environ.copy()
        env.update({str(k): str(v) for k, v in self.env.items()})
        creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            self._proc = subprocess.Popen(
                [self.command, *self.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=self.cwd,
                env=env,
                creationflags=creation,
            )
        except Exception as exc:
            raise MCPError(f"não foi possível iniciar '{self.command}': {exc}") from exc

        threading.Thread(target=self._read_loop, daemon=True, name=f"mcp-{self.name}").start()
        threading.Thread(target=self._stderr_loop, daemon=True, name=f"mcp-err-{self.name}").start()
        self._initialize()

    def _read_loop(self) -> None:
        try:
            for line in self._proc.stdout:  # type: ignore[union-attr]
                line = line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except Exception:
                    continue
                self._queue.put(message)
        except Exception as exc:
            self._queue.put({"__error__": str(exc)})
        finally:
            self._queue.put({"__closed__": True})

    def _stderr_loop(self) -> None:
        try:
            for line in self._proc.stderr:  # type: ignore[union-attr]
                line = line.strip()
                if line:
                    logs.info(f"[mcp:{self.name}] {line[:400]}")
        except Exception:
            pass

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def close(self) -> None:
        proc = self._proc
        self._proc = None
        if not proc:
            return
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    # ─── JSON-RPC ───────────────────────────────────────────

    def _send(self, payload: dict) -> None:
        if not self.alive():
            raise MCPError(f"servidor '{self.name}' não está em execução")
        try:
            self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")  # type: ignore[union-attr]
            self._proc.stdin.flush()  # type: ignore[union-attr]
        except Exception as exc:
            raise MCPError(f"falha ao enviar para '{self.name}': {exc}") from exc

    def _request(self, method: str, params: dict | None = None, timeout: float | None = None) -> dict:
        timeout = self.timeout if timeout is None else float(timeout)
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
            self._send({
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params or {},
            })
            deadline = time.time() + timeout
            while True:
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise MCPError(f"timeout ({timeout:.0f}s) em {method} @ {self.name}")
                try:
                    message = self._queue.get(timeout=remaining)
                except queue.Empty:
                    raise MCPError(f"timeout ({timeout:.0f}s) em {method} @ {self.name}")
                if message.get("__closed__"):
                    raise MCPError(f"servidor '{self.name}' encerrou a conexão")
                if message.get("__error__"):
                    raise MCPError(f"erro de leitura em '{self.name}': {message['__error__']}")
                if message.get("id") != request_id:
                    continue  # notification or unrelated response
                if "error" in message:
                    error = message["error"] or {}
                    raise MCPError(f"{error.get('message') or error} @ {self.name}")
                return message.get("result") or {}

    def _notify(self, method: str, params: dict | None = None) -> None:
        with self._lock:
            self._send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _initialize(self) -> dict:
        result = self._request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "drix", "version": "1.0"},
        })
        self.server_info = result.get("serverInfo") or {}
        try:
            self._notify("notifications/initialized")
        except Exception:
            pass
        return result

    # ─── MCP surface ────────────────────────────────────────

    def list_tools(self, refresh: bool = False) -> list[dict]:
        if self._tools is None or refresh:
            result = self._request("tools/list")
            self._tools = result.get("tools") or []
        return self._tools

    def call_tool(self, name: str, arguments: dict | None = None, timeout: float | None = None) -> str:
        result = self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
            timeout=timeout,
        )
        return _flatten(result)


class MCPManager:
    def __init__(self):
        self._clients: dict[str, MCPClient] = {}
        self._lock = threading.RLock()

    def _config(self, cfg: dict | None = None) -> dict:
        if cfg is None:
            try:
                from .main import config as main_config
                cfg = main_config.raw()
            except Exception:
                cfg = {}
        return cfg.get("mcp") or {}

    def enabled(self, cfg: dict | None = None) -> bool:
        return bool(self._config(cfg).get("enabled", False))

    def servers(self, cfg: dict | None = None) -> dict:
        return dict(self._config(cfg).get("servers") or {})

    def client(self, name: str, cfg: dict | None = None) -> MCPClient:
        servers = self.servers(cfg)
        server = servers.get(name)
        if not server:
            raise MCPError(f"servidor MCP '{name}' não configurado")
        if not server.get("enabled", True):
            raise MCPError(f"servidor MCP '{name}' desativado")

        with self._lock:
            existing = self._clients.get(name)
            if existing and existing.alive():
                return existing
            command = server.get("command")
            if not command:
                raise MCPError(f"servidor MCP '{name}' sem 'command'")
            client = MCPClient(
                name=name,
                command=command,
                args=server.get("args") or [],
                env=server.get("env") or {},
                cwd=server.get("cwd"),
                timeout=float(server.get("timeout", 30)),
            )
            client.start()
            self._clients[name] = client
            logs.info(f"MCP server '{name}' ready ({client.server_info.get('name', '?')})")
            return client

    def list_tools(self, cfg: dict | None = None, server: str | None = None) -> list[dict]:
        names = [server] if server else list(self.servers(cfg))
        out = []
        for name in names:
            try:
                client = self.client(name, cfg)
                for tool in client.list_tools(refresh=True):
                    out.append({
                        "server": name,
                        "name": tool.get("name"),
                        "description": tool.get("description") or "",
                        "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
                    })
            except Exception as exc:
                out.append({"server": name, "error": str(exc)})
        return out

    def call(self, server: str, tool: str, arguments: dict | None = None,
             cfg: dict | None = None) -> str:
        return self.client(server, cfg).call_tool(tool, arguments or {})

    def close_all(self) -> None:
        with self._lock:
            for client in self._clients.values():
                client.close()
            self._clients.clear()


manager = MCPManager()


# ─── Tool integration ────────────────────────────────────────────

def _mcp_servers(args: dict, ctx: tools.ToolContext) -> str:
    cfg = ctx.cfg or {}
    servers = manager.servers(cfg)
    payload = []
    for name, server in servers.items():
        payload.append({
            "name": name,
            "command": server.get("command"),
            "enabled": bool(server.get("enabled", True)),
            "running": bool(manager._clients.get(name) and manager._clients[name].alive()),
        })
    return json.dumps({"enabled": manager.enabled(cfg), "servers": payload}, ensure_ascii=False)


def _mcp_list_tools(args: dict, ctx: tools.ToolContext) -> str:
    cfg = ctx.cfg or {}
    if not manager.enabled(cfg):
        return "ERROR: MCP desativado (mcp.enabled=false)"
    server = args.get("server") or None
    return json.dumps({"tools": manager.list_tools(cfg, server)}, ensure_ascii=False)


def _mcp_call(args: dict, ctx: tools.ToolContext) -> str:
    cfg = ctx.cfg or {}
    if not manager.enabled(cfg):
        raise tools.ToolError("MCP desativado (mcp.enabled=false)")
    server = str(args.get("server") or "").strip()
    tool = str(args.get("tool") or "").strip()
    if not server or not tool:
        raise tools.ToolError("server e tool são obrigatórios")
    return manager.call(server, tool, args.get("arguments") or {}, cfg=cfg)


tools.register(tools.Tool(
    "mcp_servers",
    "Lista os servidores MCP configurados e se estão em execução.",
    {"type": "object", "properties": {}},
    _mcp_servers,
))

tools.register(tools.Tool(
    "mcp_list_tools",
    "Lista as ferramentas expostas pelos servidores MCP.",
    {
        "type": "object",
        "properties": {"server": {"type": "string"}},
    },
    _mcp_list_tools,
    danger="network",
))

tools.register(tools.Tool(
    "mcp_call",
    "Chama uma ferramenta de um servidor MCP configurado.",
    {
        "type": "object",
        "properties": {
            "server": {"type": "string"},
            "tool": {"type": "string"},
            "arguments": {"type": "object"},
        },
        "required": ["server", "tool"],
    },
    _mcp_call,
    danger="execute",
))
