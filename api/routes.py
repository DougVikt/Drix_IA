import sys, asyncio, re, os, threading, json, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import APIRouter, Request, UploadFile, File, Query
from fastapi.responses import JSONResponse, StreamingResponse
from . import engine as api_engine
from core.main import (
    ask, ask_stream, atualizar_aprendizado, config,
    build_warmup_messages, ConversationManager,
)
import core.agent as agent
import core.compaction as compaction
import core.downloader as downloader
import core.knowledge as knowledge
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


def _sse_token(token) -> str:
    """Guarantee SSE only ever carries plain text tokens."""
    if isinstance(token, str):
        return token
    if isinstance(token, dict):
        for key in ("t", "text", "content"):
            value = token.get(key)
            if isinstance(value, str):
                return value
    if token:
        logs.warn(f"SSE dropped non-text token: {type(token).__name__}")
    return ""


# ─── Configurações editáveis pela web ────────────────────────
# Only the keys listed here can be changed from the browser.  Engine, web and
# security internals stay out unless explicitly added below.
_SETTINGS_BOOL = {
    "history.enabled",
    "compaction.enabled",
    "compaction.use_llm",
    "engine.preload",
    "engine.watchdog",
    "engine.auto_start",
    "brain.auto_scan",
    "brain.auto_select_model",
    "local_resources.use_gpu",
    "memory.infer",
    "memory.consolidate.enabled",
    "memory.consolidate.use_llm",
    "network.allow_internet_access",
    "network.block_local_network",
    "tools.enabled",
    "skills.allow_self_create",
    "skills.speak_responses",
    "skills.transcribe_audio",
    "skills.audio_skill",
    "skills.automation_skill",
    "skills.host_automation",
    "skills.generate_images",
    "skills.image_gen_skill",
    "skills.generate_video",
    "skills.video_skill",
    "skills.vision_skill",
    "agents.enabled",
    "security.allow_host_read",
    "security.allow_host_write",
    "snapshots.enabled",
    "mcp.enabled",
    "web.auto_open",
    "web.indicator",
    "downloads.enabled",
    "knowledge.enabled",
}

_SETTINGS_INT = {
    "history.max_conversations": (1, 1000),
    "compaction.keep_recent": (0, 100),
    "compaction.max_tokens": (100, 16000),
    "engine.watchdog_interval": (1, 60),
    "brain.chunk_size": (100, 8000),
    "brain.model_params.ctx": (512, 32768),
    "brain.model_params.threads": (1, 64),
    "snapshots.max": (1, 200),
    "memory.consolidate.idle_minutes": (1, 1440),
    "memory.consolidate.interval_minutes": (1, 1440),
    "memory.consolidate.batch_size": (1, 50),
    "memory.consolidate.min_entries": (1, 500),
    "memory.consolidate.keep_recent": (0, 100),
    "memory.consolidate.max_batches_per_run": (1, 20),
    "memory.consolidate.max_tokens": (32, 4096),
    "memory.consolidate.retry_hours": (0, 720),
    "memory.block_ttl_minutes": (0, 1440),
    "network.request_timeout": (1, 300),
    "tools.max_steps": (1, 50),
    "downloads.max_concurrent": (1, 4),
    "knowledge.max_file_mb": (1, 500),
    "knowledge.chunk_size": (200, 8000),
    "knowledge.chunk_overlap": (0, 2000),
    "knowledge.top_k": (1, 20),
    "knowledge.context_chars": (200, 12000),
}

_SETTINGS_FLOAT = {
    "memory.inject_min_score": (0.0, 1.0),
    "memory.search_timeout": (0.1, 120.0),
    "memory.context_timeout": (0.1, 120.0),
}

_SETTINGS_ENUM = {
    "language": {"pt", "en", "es", "fr"},
    "tools.default_permission": {"allow", "ask", "deny"},
}

_SETTINGS_LIST = {
    "network.allowed_domains",
    "security.allowed_folders",
}

_SETTINGS_TEXT = {
    "downloads.dir",
    "knowledge.dir",
    "knowledge.db",
}

# Optional text settings: an empty value means "use the automatic default".
_SETTINGS_OPTIONAL_TEXT = {
    "downloads.cookies",
    "downloads.ffmpeg",
    "downloads.proxy",
}

_SETTINGS_KEYS = (
    _SETTINGS_BOOL | set(_SETTINGS_INT) | set(_SETTINGS_FLOAT)
    | set(_SETTINGS_ENUM) | _SETTINGS_LIST | _SETTINGS_TEXT | _SETTINGS_OPTIONAL_TEXT
    | {"engine.keep_alive"}
)


def _coerce_setting(key: str, value):
    """Validate/convert one setting. Returns (ok, coerced, error)."""
    if key == "engine.keep_alive":
        if isinstance(value, bool) or value is None:
            return False, None, "valor inválido"
        if isinstance(value, (int, float)):
            return True, int(value), None
        text = str(value).strip()
        if not text:
            return True, "30m", None
        if text.lstrip("-").isdigit():
            return True, int(text), None
        return True, text[:32], None

    if key in _SETTINGS_BOOL:
        if isinstance(value, str):
            return True, value.strip().lower() in {"1", "true", "yes", "on", "sim"}, None
        return True, bool(value), None

    if key in _SETTINGS_INT:
        low, high = _SETTINGS_INT[key]
        try:
            if isinstance(value, bool) or value is None or str(value).strip() == "":
                raise ValueError
            number = int(float(value))
        except (TypeError, ValueError):
            return False, None, "valor numérico inválido"
        if not low <= number <= high:
            return False, None, f"use um valor entre {low} e {high}"
        return True, number, None

    if key in _SETTINGS_FLOAT:
        low, high = _SETTINGS_FLOAT[key]
        try:
            if isinstance(value, bool) or value is None or str(value).strip() == "":
                raise ValueError
            number = float(value)
        except (TypeError, ValueError):
            return False, None, "valor numérico inválido"
        if not low <= number <= high:
            return False, None, f"use um valor entre {low} e {high}"
        return True, number, None

    if key in _SETTINGS_ENUM:
        text = str(value or "").strip().lower()
        if text not in _SETTINGS_ENUM[key]:
            allowed = ", ".join(sorted(_SETTINGS_ENUM[key]))
            return False, None, f"use um destes valores: {allowed}"
        return True, text, None

    if key in _SETTINGS_LIST:
        if isinstance(value, str):
            items = value.replace(",", "\n").splitlines()
        elif isinstance(value, list):
            items = value
        else:
            return False, None, "envie uma lista de valores"
        cleaned = []
        for item in items:
            text = str(item or "").strip()
            if not text:
                continue
            if len(text) > 500:
                return False, None, "cada item deve ter no máximo 500 caracteres"
            cleaned.append(text)
        if len(cleaned) > 200:
            return False, None, "máximo de 200 itens"
        return True, cleaned, None

    if key in _SETTINGS_TEXT or key in _SETTINGS_OPTIONAL_TEXT:
        if not isinstance(value, str):
            return False, None, "envie um texto"
        text = value.strip()
        if key in _SETTINGS_TEXT and not text:
            return False, None, "informe um valor"
        if len(text) > 300:
            return False, None, "texto muito longo"
        if any(ch in text for ch in ("\x00", "\n", "\r")):
            return False, None, "texto inválido"
        return True, text, None

    return False, None, "configuração não editável"


def _settings_snapshot() -> dict:
    values = {}
    for key in sorted(_SETTINGS_KEYS):
        value = config.get(*key.split("."), default=None)
        values[key] = value
    perms = config.get("tools", "permissions", default={}) or {}
    if isinstance(perms, dict):
        for name, value in perms.items():
            values[f"tools.permissions.{name}"] = value
    return values


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

_DL_QUALITY_RE = re.compile(r"(?<!\d)(144|240|360|480|720|1080|1440|2160)p?(?!\d)", re.I)


def _parse_download_args(text: str) -> tuple[str, int | None, bool]:
    """Parse ``/baixar <url> [720p] [audio]``."""
    url = ""
    quality = None
    audio_only = False
    for token in str(text or "").split():
        low = token.lower()
        if not url and re.match(r"^https?://", token, re.I):
            url = token
            continue
        if low in ("audio", "áudio", "mp3", "somente-audio", "audio-only"):
            audio_only = True
            continue
        match = _DL_QUALITY_RE.search(low)
        if match and quality is None:
            quality = int(match.group(1))
    return url, quality, audio_only


def _sse_event(payload: dict) -> str:
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


async def _download_events(url: str, quality, audio_only: bool):
    try:
        job = await asyncio.to_thread(
            downloader.start, url, quality=quality, audio_only=audio_only
        )
    except Exception as exc:
        yield _sse_event({"t": f"Erro: {exc}"})
        yield "data: [DONE]\n\n"
        return

    yield _sse_event({"t": f"Baixando: {job['url']}\n"})
    started = time.time()
    last_bucket = -1
    last_update = 0.0
    current = job

    while time.time() - started < 1800:
        await asyncio.sleep(2)
        fresh = downloader.status(job["id"])
        if not fresh:
            break
        current = fresh
        if fresh["status"] in ("done", "error", "cancelled"):
            break
        if fresh["status"] == "downloading":
            bucket = int(float(fresh.get("progress") or 0) // 25)
            now = time.time()
            if bucket != last_bucket or now - last_update >= 15:
                yield _sse_event({"t": downloader.describe(fresh) + "\n"})
                last_bucket = bucket
                last_update = now
        elif fresh["status"] == "processing" and last_bucket != 99:
            yield _sse_event({"t": downloader.describe(fresh) + "\n"})
            last_bucket = 99

    yield _sse_event({"t": downloader.describe(downloader.status(job["id"]) or current) + "\n"})
    yield "data: [DONE]\n\n"


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

    if cmd in ("/baixar", "/download") or cmd.startswith("/baixar ") or cmd.startswith("/download "):
        arg = text.split(" ", 1)[1].strip() if " " in text else ""
        url, quality, audio_only = _parse_download_args(arg)
        if not url:
            return {"text": "Use: /baixar <link> [720p] [audio]", "type": "system"}
        stream = body.get("stream", False)
        if stream:
            return StreamingResponse(
                _download_events(url, quality, audio_only),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        try:
            job = downloader.start(url, quality=quality, audio_only=audio_only)
        except Exception as exc:
            return {"text": f"Erro: {exc}", "type": "system"}
        job = await asyncio.to_thread(downloader.wait, job["id"], 60)
        return {"text": downloader.describe(job), "type": "system"}

    stream = body.get("stream", False)

    if stream:
        async def _event_stream():
            runtime.chat_begin()
            try:
                async with _chat_lock:
                    conv_mgr.set_workspace(workspace)
                    try:
                        async for token in ask_stream(text, conv_mgr):
                            token = _sse_token(token)
                            if not token:
                                continue
                            # JSON keeps newlines and quotes intact inside SSE.
                            yield "data: " + json.dumps(
                                {"t": token}, ensure_ascii=False
                            ) + "\n\n"
                        yield "data: [DONE]\n\n"
                    except Exception as e:
                        yield "data: " + json.dumps(
                            {"error": str(e)}, ensure_ascii=False
                        ) + "\n\n"
            finally:
                runtime.chat_end()
        return StreamingResponse(
            _event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    runtime.chat_begin()
    try:
        async with _chat_lock:
            conv_mgr.set_workspace(workspace)
            try:
                resp = await ask(text, conv_mgr)
                return {"text": resp, "type": "ai", "model": config.get("brain", "local_model", default="")}
            except Exception as e:
                return {"text": f"Error: {e}", "type": "system"}
    finally:
        runtime.chat_end()


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
    ok, err = config.set_many(
        {"brain.auto_select_model": False, "brain.local_model": name},
        force=False,
    )
    if not ok:
        return JSONResponse({"detail": err}, status_code=400)
    # Warm the new model in the background with the current conversation
    # prefix.  The builder runs after any active answer finishes, so the
    # preload sees the final history and the first reply is fast.
    is_local = False
    try:
        is_local = providers.resolve().provider in ("local", "ollama")
    except Exception:
        pass
    warming = False
    if is_local:
        try:
            warming = api_engine.request_preload(
                name,
                message_builder=lambda: build_warmup_messages(conv_mgr),
            )
        except Exception as exc:
            logs.warn(f"Model warmup queue failed: {exc}")
    warning = ""
    if is_local and not warming and not api_engine.model_fits_ram(name):
        warning = (
            "Modelo grande para a RAM disponível; será carregado na "
            "primeira mensagem e pode demorar."
        )
    return {
        "status": "selected",
        "name": name,
        "warming": warming,
        "warning": warning,
    }

@router.post("/models/preload")
async def preload_model(req: Request):
    body = await req.json()
    name = _clean_name(body.get("name", ""), max_len=200, extra_chars=":")
    if not name:
        return JSONResponse({"detail": "Name required or invalid"}, status_code=400)
    ok = await asyncio.to_thread(api_engine.preload_model, name)
    return {"model": name, "preloaded": bool(ok)}

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


# ─── Downloads ───────────────────────────────────────────────

@router.get("/downloads")
async def downloads_list():
    return {"jobs": downloader.list_jobs(50), "info": downloader.info()}


@router.post("/downloads/probe")
async def downloads_probe(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"detail": "Corpo inválido"}, status_code=400)
    url = _clean_text(body.get("url", ""), 4096)
    if not url:
        return JSONResponse({"detail": "URL obrigatória"}, status_code=400)
    try:
        data = await asyncio.to_thread(downloader.probe, url)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)[:400]}, status_code=400)
    return data


@router.post("/downloads")
async def downloads_start(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"detail": "Corpo inválido"}, status_code=400)
    url = _clean_text(body.get("url", ""), 4096)
    if not url:
        return JSONResponse({"detail": "URL obrigatória"}, status_code=400)
    quality = None
    raw_quality = body.get("quality")
    if raw_quality not in (None, ""):
        try:
            quality = int(raw_quality)
        except (TypeError, ValueError):
            return JSONResponse({"detail": "Qualidade inválida"}, status_code=400)
        if not 144 <= quality <= 2160:
            return JSONResponse({"detail": "Qualidade fora do intervalo"}, status_code=400)
    try:
        job = downloader.start(
            url,
            quality=quality,
            audio_only=bool(body.get("audio_only")),
            workspace=str(body.get("workspace") or "default"),
        )
    except Exception as exc:
        return JSONResponse({"detail": str(exc)[:400]}, status_code=400)
    return job


@router.delete("/downloads")
async def downloads_clear():
    return {"removed": downloader.clear_finished()}


@router.get("/downloads/{job_id}")
async def downloads_status(job_id: str):
    job = downloader.status(job_id)
    if not job:
        return JSONResponse({"detail": "Download não encontrado"}, status_code=404)
    return job


@router.delete("/downloads/{job_id}")
async def downloads_cancel(job_id: str):
    if not downloader.cancel(job_id):
        return JSONResponse({"detail": "Download não encontrado ou já finalizado"},
                            status_code=404)
    return {"status": "cancelling", "id": job_id}


# ─── Knowledge base ──────────────────────────────────────────

@router.get("/knowledge")
async def knowledge_list():
    return {
        "documents": knowledge.list_documents(200),
        "info": knowledge.info(),
    }


@router.post("/knowledge/upload")
async def knowledge_upload(file: UploadFile = File(...)):
    data = await file.read()
    try:
        doc = await asyncio.to_thread(
            knowledge.add_document, file.filename or "documento", data
        )
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception as exc:
        logs.warn(f"Knowledge upload failed: {exc}")
        return JSONResponse({"detail": "Falha ao salvar o documento"}, status_code=500)
    return doc


@router.post("/knowledge/reindex")
async def knowledge_reindex(req: Request):
    try:
        body = await req.json()
    except Exception:
        body = {}
    doc_id = _clean_text(body.get("id", ""), 64) if isinstance(body, dict) else ""
    try:
        result = await asyncio.to_thread(knowledge.reindex, doc_id or None)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return result


@router.post("/knowledge/search")
async def knowledge_search(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"detail": "Corpo inválido"}, status_code=400)
    query = _clean_text(body.get("query", ""), 2000)
    if not query:
        return JSONResponse({"detail": "Pergunta obrigatória"}, status_code=400)
    try:
        k = int(body.get("k") or 4)
    except (TypeError, ValueError):
        k = 4
    results = await asyncio.to_thread(knowledge.search, query, k)
    return {"query": query, "count": len(results), "results": results}


@router.get("/knowledge/{doc_id}")
async def knowledge_status(doc_id: str):
    doc = knowledge.status(doc_id)
    if not doc:
        return JSONResponse({"detail": "Documento não encontrado"}, status_code=404)
    return doc


@router.delete("/knowledge/{doc_id}")
async def knowledge_delete(doc_id: str):
    ok = await asyncio.to_thread(knowledge.delete_document, doc_id)
    if not ok:
        return JSONResponse({"detail": "Documento não encontrado"}, status_code=404)
    return {"deleted": doc_id}


# ─── Memory ──────────────────────────────────────────────────

@router.post("/memory/search")
async def memory_search(req: Request):
    body = await req.json()
    query = _clean_text(body.get("query", ""), 2000)
    try:
        limit = int(body.get("limit", 5) or 5)
    except (TypeError, ValueError):
        limit = 5
    limit = max(1, min(limit, 50))
    if not query:
        return JSONResponse({"detail": "Query required or too long"}, status_code=400)
    try:
        import core.memory as mem
        if body.get("scored"):
            items = await asyncio.to_thread(mem.search_scored, query, limit, 0.0)
            return {"results": items[:limit], "count": len(items)}
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
        items = all_mem.get("results", []) if isinstance(all_mem, dict) else all_mem
        return {"memories": items, "count": len(items)}
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=500)

@router.post("/memory/reset")
async def memory_reset():
    try:
        import core.memory as mem
        mem.reset()
        from core.main import _invalidate_memory_cache
        _invalidate_memory_cache()
        return {"status": "reset"}
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=500)


@router.get("/memory/consolidation")
async def memory_consolidation_status():
    try:
        import core.memory_maintenance as maintenance
        return await asyncio.to_thread(maintenance.status)
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=500)


@router.post("/memory/consolidation/run")
async def memory_consolidation_run(req: Request):
    body = {}
    try:
        body = await req.json()
    except Exception:
        pass
    try:
        import core.memory_maintenance as maintenance
        return maintenance.request_now(force=bool(body.get("force", False)))
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
        "version": "0.1.0",
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
    if "timeout" in body:
        try:
            timeout = float(body["timeout"])
        except (TypeError, ValueError):
            return JSONResponse({"detail": "timeout inválido"}, status_code=400)
        if not 5 <= timeout <= 600:
            return JSONResponse({"detail": "timeout deve ficar entre 5 e 600 segundos"},
                                status_code=400)
        updates["operation.timeout"] = timeout
    if "keep_alive" in body:
        raw = body.get("keep_alive")
        if isinstance(raw, bool) or raw is None:
            return JSONResponse({"detail": "keep_alive inválido"}, status_code=400)
        if isinstance(raw, (int, float)):
            updates["operation.keep_alive"] = int(raw)
        else:
            text = str(raw).strip()
            if not text:
                updates["operation.keep_alive"] = "30m"
            elif text.lstrip("-").isdigit():
                updates["operation.keep_alive"] = int(text)
            else:
                updates["operation.keep_alive"] = text[:32]
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


# ─── Settings (painel web) ───────────────────────────────────

@router.get("/settings")
async def get_settings():
    return {
        "settings": _settings_snapshot(),
        "editable": sorted(_SETTINGS_KEYS),
        "language": lang.current(),
        "engine": {
            "host": config.get("engine", "host", default="127.0.0.1"),
            "port": config.get("engine", "port", default=11434),
            "auto_start": config.get("engine", "auto_start", default=True),
        },
    }


@router.post("/settings")
async def update_settings(req: Request):
    try:
        body = await req.json()
    except Exception:
        return JSONResponse({"detail": "Corpo inválido"}, status_code=400)

    incoming = body.get("settings") if isinstance(body, dict) else None
    if not isinstance(incoming, dict) or not incoming:
        return JSONResponse({"detail": "Nenhuma configuração enviada"}, status_code=400)
    if len(incoming) > 100:
        return JSONResponse({"detail": "Configurações demais em uma só requisição"},
                            status_code=400)

    updates = {}
    errors = {}
    for key, raw in incoming.items():
        key = str(key or "").strip()
        if key.startswith("tools.permissions.") and key.count(".") == 2:
            tool_name = key.rsplit(".", 1)[1]
            if not re.fullmatch(r"[A-Za-z0-9_\-]{1,60}", tool_name):
                errors[key] = "nome de ferramenta inválido"
                continue
            ok, value, error = _coerce_setting("tools.default_permission", raw)
            if not ok:
                errors[key] = error
                continue
            updates[key] = value
            continue
        if key not in _SETTINGS_KEYS:
            errors[key or "?"] = "configuração não editável"
            continue
        ok, value, error = _coerce_setting(key, raw)
        if not ok:
            errors[key] = error
            continue
        updates[key] = value

    if "knowledge.chunk_size" in updates or "knowledge.chunk_overlap" in updates:
        try:
            size = int(updates.get("knowledge.chunk_size",
                                   config.get("knowledge", "chunk_size", default=1000)))
            overlap = int(updates.get("knowledge.chunk_overlap",
                                      config.get("knowledge", "chunk_overlap", default=200)))
            if overlap >= size:
                errors["knowledge.chunk_overlap"] = "deve ser menor que chunk_size"
        except (TypeError, ValueError):
            errors["knowledge.chunk_size"] = "valor inválido"

    if errors:
        return JSONResponse(
            {"detail": "Alguns valores são inválidos", "errors": errors},
            status_code=400,
        )
    if not updates:
        return {"status": "unchanged", "updated": []}

    ok, err = config.set_many(updates, force=True)
    if not ok:
        return JSONResponse({"detail": err or "Falha ao salvar"}, status_code=400)

    config.reload()
    if "language" in updates:
        lang.set_language(updates["language"])
    if any(key.startswith("memory.") for key in updates):
        try:
            from core.main import _invalidate_memory_cache
            _invalidate_memory_cache()
        except Exception:
            pass
    if any(key.startswith("knowledge.") for key in updates):
        knowledge.reset_cache()

    logs.info(f"Settings updated: {', '.join(sorted(updates))}")
    return {
        "status": "saved",
        "updated": sorted(updates),
        "settings": _settings_snapshot(),
    }


# ─── Runtime / lifecycle ─────────────────────────────────────


# ─── Runtime / lifecycle ─────────────────────────────────────

@router.get("/runtime")
async def runtime_state():
    return JSONResponse(runtime.status(), headers={"Cache-Control": "no-store"})


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
        runtime.begin_stop()
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
    runtime.chat_begin()
    try:
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
    finally:
        runtime.chat_end()

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
        runtime.chat_begin()
        try:
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
        finally:
            runtime.chat_end()

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
