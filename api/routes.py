import sys, asyncio, re, os, threading, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import APIRouter, Request, UploadFile, File, Query
from fastapi.responses import JSONResponse, StreamingResponse
from . import engine as api_engine
from core.main import (
    ask, ask_stream, atualizar_aprendizado, config,
    ConversationManager,
)
import core.agent as agent
import core.compaction as compaction
import core.language as lang
import core.mcp as mcp
import core.media as media
import core.providers as providers
import core.runtime as runtime
import core.secrets as secrets
import core.snapshots as snapshots
import core.subagents as subagents
import core.tools as tools
import core.web as web
import core.logs as logs

media.init_cache()

conv_mgr = ConversationManager(db_path="./data/web_conversations.db")
conv_mgr.set_workspace("default")

router = APIRouter()
_chat_lock = asyncio.Lock()


def _clean_name(value, max_len=100, extra_chars=""):
    value = (value or "").strip()
    if not value or len(value) > max_len:
        return ""
    charset = r"\w\- ." + re.escape(extra_chars)
    if not re.fullmatch(rf"[{charset}]+", value, flags=re.UNICODE):
        return ""
    return value


def _clean_text(value, max_len):
    value = (value or "").strip()
    if len(value) > max_len:
        return ""
    return value


# ─── Engine ──────────────────────────────────────────────────

@router.get("/engine")
async def engine_status():
    return {"running": api_engine.port_in_use()}

@router.post("/engine/start")
async def engine_start():
    ok = api_engine.start()
    if ok:
        api_engine.sync_models()
        config.reload()
    return {"status": "started" if ok else "failed"}

@router.post("/engine/stop")
async def engine_stop():
    api_engine.stop()
    return {"status": "stopped"}

@router.post("/engine/restart")
async def engine_restart():
    api_engine.stop()
    ok = api_engine.start()
    return {"status": "restarted" if ok else "failed"}


# ─── Workspaces ──────────────────────────────────────────────

@router.get("/workspaces")
async def list_workspaces():
    ws = conv_mgr.list_workspaces()
    return {"workspaces": [{"name": w[0], "created_at": w[1], "updated_at": w[2]} for w in ws]}

@router.post("/workspaces")
async def create_workspace(req: Request):
    body = await req.json()
    name = _clean_name(body.get("name", ""))
    if not name:
        return JSONResponse({"detail": "Name required or invalid"}, status_code=400)
    async with _chat_lock:
        conv_mgr.set_workspace(name)
    return {"name": name}

@router.delete("/workspaces/{name:path}")
async def delete_workspace(name: str):
    name = _clean_name(name)
    if not name:
        return JSONResponse({"detail": "Name invalid"}, status_code=400)
    async with _chat_lock:
        ok = conv_mgr.delete_workspace(name)
    if not ok:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return {"deleted": name}

@router.put("/workspaces/{name:path}")
async def rename_workspace(name: str, req: Request):
    body = await req.json()
    new_name = _clean_name(body.get("new_name", ""))
    if not new_name:
        return JSONResponse({"detail": "new_name required or invalid"}, status_code=400)
    async with _chat_lock:
        ok = conv_mgr.rename_workspace(name, new_name)
    if not ok:
        return JSONResponse({"detail": "Rename failed"}, status_code=400)
    return {"old_name": name, "new_name": new_name}

@router.get("/workspaces/{name:path}/messages")
async def get_messages(name: str, limit: int = Query(50)):
    if limit < 1 or limit > 500:
        limit = 50
    msgs = conv_mgr.get_history_for(name, limit)
    return {"messages": [{"role": m[0], "content": m[1]} for m in msgs]}

@router.post("/workspaces/{name:path}/select")
async def select_workspace(name: str):
    async with _chat_lock:
        ok = conv_mgr.set_workspace(name)
    if not ok:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return {"name": name}


# ─── Chat ────────────────────────────────────────────────────

@router.post("/chat")
async def chat(req: Request):
    body = await req.json()
    text = _clean_text(body.get("message", ""), 10000)
    workspace = body.get("workspace", "default")
    if not text:
        return {"text": "", "type": "system"}

    cmd = text.lower()

    if cmd in ["/learn", "/aprender"]:
        atualizar_aprendizado()
        return {"text": lang.get("ui_sync_ok"), "type": "system"}

    if cmd in ["/clear", "/limpar"]:
        return {"text": "", "type": "clear"}

    if cmd.startswith("/lang "):
        new_lang = cmd[6:].strip()
        if lang.set_language(new_lang):
            return {"text": lang.get("lang_switched"), "type": "lang", "title": lang.get("ui_title")}
        return {"text": lang.get("lang_invalid"), "type": "system"}

    if cmd in ["/sync", "/sincronizar"]:
        import core.config_auto as config_auto
        changes = config_auto.sync_all()
        config.reload()
        active = [c for c in changes if c]
        text = "; ".join(active) if active else "No changes detected."
        return {"text": f"Sync: {text}", "type": "system"}

    stream = body.get("stream", False)

    if stream:
        async def _event_stream():
            async with _chat_lock:
                conv_mgr.set_workspace(workspace)
                try:
                    async for token in ask_stream(text, conv_mgr):
                        yield f"data: {token}\n\n"
                    yield "data: [DONE]\n\n"
                except Exception as e:
                    yield f"data: Error: {e}\n\n"
        return StreamingResponse(_event_stream(), media_type="text/event-stream")

    async with _chat_lock:
        conv_mgr.set_workspace(workspace)
        try:
            resp = await ask(text, conv_mgr)
            return {"text": resp, "type": "ai", "model": config.get("brain", "local_model", default="")}
        except Exception as e:
            return {"text": f"Error: {e}", "type": "system"}


# ─── Models ──────────────────────────────────────────────────

@router.get("/models")
async def list_models():
    models = config.get("brain", "installed_models", default=[])
    selected = config.get("brain", "local_model", default="")
    return {"models": models, "selected": selected}

@router.post("/models/pull")
async def pull_model(req: Request):
    body = await req.json()
    name = _clean_name(body.get("name", ""), max_len=200, extra_chars=":")
    if not name:
        return JSONResponse({"detail": "Name required or invalid"}, status_code=400)
    try:
        import ollama
        ollama.pull(name)
        return {"status": "pulled", "name": name}
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=400)

@router.post("/models/select")
async def select_model(req: Request):
    body = await req.json()
    name = _clean_name(body.get("name", ""), max_len=200, extra_chars=":")
    if not name:
        return JSONResponse({"detail": "Name required or invalid"}, status_code=400)
    ok, err = config.set("brain.auto_select_model", False)
    if not ok:
        return JSONResponse({"detail": err}, status_code=400)
    ok, err = config.set("brain.local_model", name)
    if not ok:
        return JSONResponse({"detail": err}, status_code=400)
    return {"status": "selected", "name": name}

@router.delete("/models/{name:path}")
async def delete_model(name: str):
    name = _clean_name(name, max_len=200, extra_chars=":")
    if not name:
        return JSONResponse({"detail": "Name invalid"}, status_code=400)
    try:
        import ollama
        ollama.delete(name)
        return {"deleted": name}
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=400)


# ─── Memory ──────────────────────────────────────────────────

@router.post("/memory/search")
async def memory_search(req: Request):
    body = await req.json()
    query = _clean_text(body.get("query", ""), 2000)
    limit = min(body.get("limit", 5), 50)
    if not query:
        return JSONResponse({"detail": "Query required or too long"}, status_code=400)
    try:
        import core.memory as mem
        from core.main import _search_memories
        results = await asyncio.to_thread(_search_memories, query)
        return {"results": results[:limit], "count": len(results)}
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=500)

@router.get("/memory/all")
async def memory_all():
    try:
        import core.memory as mem
        all_mem = await asyncio.to_thread(mem.get_all)
        return {"memories": all_mem, "count": len(all_mem)}
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=500)

@router.post("/memory/reset")
async def memory_reset():
    try:
        import core.memory as mem
        mem.reset()
        return {"status": "reset"}
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=500)


# ─── Web Search ──────────────────────────────────────────────

@router.post("/buscar")
async def web_search(req: Request):
    body = await req.json()
    query = _clean_text(body.get("query", ""), 500)
    if not query:
        return JSONResponse({"detail": "Query required or too long"}, status_code=400)
    results = web.search(query)
    return {"results": results, "count": len(results)}

@router.post("/site")
async def web_fetch(req: Request):
    body = await req.json()
    url = body.get("url", "").strip()
    if not url or len(url) > 2048:
        return JSONResponse({"detail": "URL required or too long"}, status_code=400)
    try:
        web.check_url(url)
    except ValueError as e:
        logs.warn(f"WEB blocked url={url[:200]!r}: {e}")
        return JSONResponse({"detail": f"Blocked: {e}"}, status_code=400)
    content = web.fetch(url)
    return {"content": content, "length": len(content)}


# ─── Upload / Mídia ──────────────────────────────────────────

@router.post("/upload")
async def upload_file(file: UploadFile = File(...), workspace: str = "default"):
    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        return JSONResponse({"detail": "File too large (max 50 MB)"}, status_code=413)
    name = (file.filename or "file").replace("\\", "/").rsplit("/", 1)[-1].strip()
    name = _clean_name(name, max_len=255, extra_chars="()[]+")
    if not name:
        return JSONResponse({"detail": "Filename invalid"}, status_code=400)
    safe_name, path = media.save_file(data, name, workspace)
    return {"name": safe_name, "path": path, "size": len(data), "type": file.content_type}

@router.get("/attachments")
async def list_attachments(workspace: str = "default"):
    return {"files": media.list_files(workspace)}

@router.delete("/attachments/{filename:path}")
async def delete_attachment(filename: str, workspace: str = "default"):
    ok = media.delete_file(filename, workspace)
    if not ok:
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return {"deleted": filename}


# ─── Sistema ─────────────────────────────────────────────────

@router.get("/status")
async def system_status():
    import core.hardware as hardware
    hw = hardware.analyze()
    return {
        "version": "1.0",
        "mode": config.get("operation", "mode", default="local"),
        "engine_running": api_engine.port_in_use(),
        "hardware": {
            "ram_gb": hw.get("ram_gb"),
            "cpu_cores": hw.get("cpu_cores"),
            "selected_model": hw.get("selected_model"),
        },
    }

@router.get("/logs")
async def get_logs(lines: int = Query(50)):
    log_file = Path(__file__).resolve().parent.parent / "logs" / "drix.log"
    if not log_file.exists():
        return {"logs": []}
    content = log_file.read_text(encoding="utf-8").strip().split("\n")
    return {"logs": content[-lines:]}

@router.post("/sync")
async def sync_config():
    import core.config_auto as config_auto
    changes = config_auto.sync_all()
    config.reload()
    active = [c for c in changes if c]
    return {"changes": active}


# ─── Providers ───────────────────────────────────────────────

@router.get("/providers")
async def providers_info():
    return {
        "catalog": providers.provider_catalog(),
        "current": providers.describe(),
        "encryption": secrets.encryption_mode(),
    }


@router.post("/providers/config")
async def providers_config(req: Request):
    body = await req.json()
    provider = str(body.get("provider") or "").strip().lower()
    valid = {p["id"] for p in providers.provider_catalog()}
    if provider not in valid:
        return JSONResponse({"detail": "Provider desconhecido"}, status_code=400)

    if "api_key" in body:
        try:
            secrets.set_secret(providers.secret_name(provider), str(body.get("api_key") or ""))
        except Exception as exc:
            return JSONResponse({"detail": f"Não foi possível guardar a chave: {exc}"},
                                status_code=500)

    updates = {
        "operation.provider": provider,
        "operation.mode": "local" if provider == "local" else "api",
    }
    if "model" in body:
        updates["operation.model"] = str(body.get("model") or "").strip()
    if "base_url" in body:
        updates["operation.base_url"] = str(body.get("base_url") or "").strip()
    if "temperature" in body:
        try:
            updates["operation.temperature"] = float(body["temperature"])
        except (TypeError, ValueError):
            return JSONResponse({"detail": "temperature inválida"}, status_code=400)
    if "max_tokens" in body:
        try:
            updates["operation.max_tokens"] = int(body["max_tokens"])
        except (TypeError, ValueError):
            return JSONResponse({"detail": "max_tokens inválido"}, status_code=400)
    if "fallback_local" in body:
        updates["operation.fallback_local"] = bool(body["fallback_local"])

    ok, err = config.set_many(updates, force=True)
    if not ok:
        return JSONResponse({"detail": err}, status_code=400)
    config.reload()
    return {"status": "saved", "current": providers.describe()}


@router.post("/providers/test")
async def providers_test():
    try:
        return await providers.test_connection()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@router.delete("/providers/{provider}/key")
async def providers_delete_key(provider: str):
    provider = str(provider or "").strip().lower()
    removed = secrets.delete_secret(providers.secret_name(provider))
    return {"deleted": removed, "provider": provider}


# ─── Runtime / lifecycle ─────────────────────────────────────

@router.get("/runtime")
async def runtime_state():
    return runtime.status()


@router.post("/runtime/indicator")
async def runtime_indicator():
    pid = runtime.spawn_indicator()
    return {"indicator_pid": pid, "status": "started" if pid else "failed"}


@router.post("/runtime/stop")
async def runtime_stop(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    targets = body.get("targets") or ["engine"]
    result = {}

    if "engine" in targets:
        runtime.stop_engine()
        result["engine"] = "stopped"
    if "indicator" in targets:
        result["indicator"] = "stopped" if runtime.stop_indicator() else "not-running"
    if "web" in targets:
        result["web"] = "stopping"
        # Respond first, then exit. The lifespan shutdown is skipped on purpose
        # so the engine keeps running unless it was explicitly stopped above.
        threading.Timer(0.6, lambda: os._exit(0)).start()

    return result

# ─── Agent / Tools ───────────────────────────────────────────

@router.get("/tools")
async def list_tools():
    cfg = config.raw()
    return {
        "enabled": (cfg.get("tools") or {}).get("enabled", True),
        "tools": [
            {**schema, "permission": tools.permission_for(schema["name"], cfg)}
            for schema in tools.schemas()
        ],
    }


def _agent_request(body: dict) -> tuple[str, str, frozenset, bool]:
    text = _clean_text(body.get("message", ""), 10000)
    workspace = str(body.get("workspace") or "default")
    token = str(body.get("approval_token") or "").strip()
    approvals = frozenset({token}) if token else frozenset()
    use_tools = bool(body.get("tools", True))
    return text, workspace, approvals, use_tools


@router.post("/agent")
async def agent_run(req: Request):
    body = await req.json()
    text, workspace, approvals, use_tools = _agent_request(body)
    if not text:
        return {"text": "", "type": "system"}

    final = ""
    events = []
    async with _chat_lock:
        conv_mgr.set_workspace(workspace)
        async for event in agent.run(
            text, conv_mgr, workspace=workspace, approvals=approvals, use_tools=use_tools,
        ):
            kind = event.get("type")
            if kind == "final":
                final = event.get("text") or ""
            elif kind == "error":
                return JSONResponse(
                    {"text": f"Error: {event.get('message')}", "type": "system"},
                    status_code=500,
                )
            elif kind == "approval_required":
                return JSONResponse(event, status_code=202)
            elif kind in ("tool_call", "tool_result"):
                events.append(event)

    return {
        "text": final,
        "type": "ai",
        "events": events,
        "model": providers.describe().get("model", ""),
    }


@router.post("/agent/stream")
async def agent_stream(req: Request):
    body = await req.json()
    text, workspace, approvals, use_tools = _agent_request(body)
    if not text:
        return {"text": "", "type": "system"}

    async def _events():
        async with _chat_lock:
            conv_mgr.set_workspace(workspace)
            try:
                async for event in agent.run(
                    text, conv_mgr, workspace=workspace,
                    approvals=approvals, use_tools=use_tools,
                ):
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

    return StreamingResponse(_events(), media_type="text/event-stream")


# ─── Snapshots ───────────────────────────────────────────────

@router.get("/snapshots")
async def snapshots_list():
    return {
        "snapshots": snapshots.list_snapshots(50),
        "total_bytes": snapshots.total_size(),
    }


@router.post("/snapshots")
async def snapshots_create(req: Request):
    body = await req.json()
    paths = body.get("paths") or []
    if not isinstance(paths, list) or not paths:
        return JSONResponse({"detail": "paths é obrigatório"}, status_code=400)
    manifest = snapshots.create(paths, label=str(body.get("label") or "manual"))
    return manifest


@router.get("/snapshots/{snapshot_id}")
async def snapshots_diff(snapshot_id: str):
    return snapshots.diff(snapshot_id)


@router.post("/snapshots/{snapshot_id}/restore")
async def snapshots_restore(snapshot_id: str):
    allow_external = bool((config.raw().get("security") or {}).get("allow_host_write", False))
    result = snapshots.restore(snapshot_id, allow_external=allow_external)
    if result.get("error"):
        return JSONResponse(result, status_code=404)
    return result


@router.delete("/snapshots/{snapshot_id}")
async def snapshots_delete(snapshot_id: str):
    if not snapshots.delete(snapshot_id):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    return {"deleted": snapshot_id}


# ─── Subagents ───────────────────────────────────────────────

@router.get("/subagents")
async def subagents_list():
    return {"subagents": subagents.catalog(config.raw())}


@router.post("/subagents/run")
async def subagents_run(req: Request):
    body = await req.json()
    name = str(body.get("agent") or "").strip().lower()
    task = _clean_text(body.get("task", ""), 8000)
    if not name or not task:
        return JSONResponse({"detail": "agent e task são obrigatórios"}, status_code=400)
    workspace = str(body.get("workspace") or "default")
    try:
        result = await subagents.run_subagent(
            name, task, cfg=config.raw(), workspace=workspace
        )
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=500)
    return {"agent": name, "text": result}


# ─── Compaction ──────────────────────────────────────────────

@router.get("/compaction/{workspace:path}")
async def compaction_status(workspace: str):
    summary = conv_mgr.get_summary(workspace)
    rows = conv_mgr.get_all_history_for(workspace)
    total = sum(compaction.estimate_tokens(row[2]) for row in rows)
    limits = config.raw().get("compaction") or {}
    return {
        "workspace": workspace,
        "messages": len(rows),
        "estimated_tokens": total,
        "max_tokens": limits.get("max_tokens", 3000),
        "summary": summary,
    }


@router.post("/compaction/{workspace:path}")
async def compaction_run(workspace: str):
    async with _chat_lock:
        result = await compaction.maybe_compact(
            conv_mgr, workspace, cfg=config.raw(), force=True
        )
    if not result:
        return {"status": "nothing_to_compact", "workspace": workspace}
    return {"status": "compacted", **result}


@router.delete("/compaction/{workspace:path}")
async def compaction_clear(workspace: str):
    ok = conv_mgr.clear_summary(workspace)
    return {"cleared": ok, "workspace": workspace}


# ─── MCP ─────────────────────────────────────────────────────

@router.get("/mcp/servers")
async def mcp_servers():
    cfg = config.raw()
    return {
        "enabled": mcp.manager.enabled(cfg),
        "servers": mcp.manager.servers(cfg),
    }


@router.get("/mcp/tools")
async def mcp_tools(server: str | None = Query(None)):
    cfg = config.raw()
    if not mcp.manager.enabled(cfg):
        return {"enabled": False, "tools": []}
    return {"enabled": True, "tools": mcp.manager.list_tools(cfg, server)}


@router.post("/mcp/call")
async def mcp_call(req: Request):
    body = await req.json()
    cfg = config.raw()
    if not mcp.manager.enabled(cfg):
        return JSONResponse({"detail": "MCP desativado (mcp.enabled=false)"}, status_code=400)
    server = str(body.get("server") or "").strip()
    tool = str(body.get("tool") or "").strip()
    if not server or not tool:
        return JSONResponse({"detail": "server e tool são obrigatórios"}, status_code=400)
    try:
        text = mcp.manager.call(server, tool, body.get("arguments") or {}, cfg=cfg)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return {"server": server, "tool": tool, "result": text}
