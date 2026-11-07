import contextlib
import os
import sys
import threading
import time
from pathlib import Path
from . import logs

HD_ROOT = Path(__file__).resolve().parent.parent
MEM0_DIR = HD_ROOT / "data" / "mem0"
_memory = None
_failed_at = 0.0
_RETRY_SECONDS = 300
_init_lock = threading.Lock()
# Mem0's local Qdrant store is not safe for concurrent writes/searches.  The
# web service runs chat memory and the idle consolidation thread in the same
# process, so serialise every operation on the client.
_memory_lock = threading.RLock()


@contextlib.contextmanager
def _quiet():
    """Hide noisy Mem0/PostHog writes on stderr (existing behaviour)."""
    old = sys.stderr
    sys.stderr = None
    try:
        yield
    finally:
        sys.stderr = old


def _role_of(item: dict) -> str:
    role = item.get("role")
    if not role:
        role = (item.get("metadata") or {}).get("role")
    return str(role or "").lower()


def _kind_of(item: dict) -> str:
    return str((item.get("metadata") or {}).get("kind") or "").lower()


def _get_model():
    from . import hardware
    hw = hardware.analyze()
    return hw.get("selected_model", "phi3.5:3.8b")


def get_memory():
    if _memory is not None:
        return _memory
    with _init_lock:
        return _get_memory_locked()


def _get_memory_locked():
    global _memory, _failed_at
    if _memory is not None:
        return _memory
    if _failed_at and (time.time() - _failed_at) < _RETRY_SECONDS:
        return None
    os.environ.setdefault("MEM0_TELEMETRY", "false")
    import logging
    logging.getLogger("mem0").setLevel(logging.ERROR)
    import warnings
    warnings.filterwarnings("ignore", message=".*PostHog.*")
    warnings.filterwarnings("ignore", message=".*spaCy.*")
    warnings.filterwarnings("ignore", message=".*fastembed.*")
    warnings.filterwarnings("ignore", message=".*SelectableGroups.*")
    _stderr = sys.stderr
    sys.stderr = None
    try:
        from mem0 import Memory
        from mem0.configs.base import MemoryConfig
        MEM0_DIR.mkdir(parents=True, exist_ok=True)
        config = MemoryConfig(
        llm={
            "provider": "ollama",
            "config": {
                "model": _get_model(),
                "ollama_base_url": "http://127.0.0.1:11434",
                "temperature": 0.1,
            },
        },
            embedder={
                "provider": "ollama",
                "config": {
                    "model": "nomic-embed-text",
                    "ollama_base_url": "http://127.0.0.1:11434",
                    "embedding_dims": 768,
                },
            },
            vector_store={
                "provider": "qdrant",
                "config": {
                    "path": str(MEM0_DIR / "qdrant"),
                    "collection_name": "drix_memories",
                    "embedding_model_dims": 768,
                },
            },
            history_db_path=str(MEM0_DIR / "history.db"),
            version="v1.1",
        )
        _memory = Memory(config=config)
        _failed_at = 0.0
    except Exception as e:
        logs.warn(f"Mem0 init failed: {e}")
        _memory = None
        _failed_at = time.time()
    finally:
        sys.stderr = _stderr
    return _memory


def add(conversation_turn, infer: bool = False):
    """Store a conversation turn.

    ``infer=False`` embeds the raw messages directly; it is fast and does not
    call the chat model.  ``infer=True`` asks Mem0 to extract facts, which is
    much slower on CPU-only machines and can delay the next answer.
    """
    m = get_memory()
    if m is None:
        return
    messages = [
        {"role": "user", "content": conversation_turn["user"]},
        {"role": "assistant", "content": conversation_turn["assistant"]},
    ]
    if not str(messages[1]["content"]).strip():
        messages = messages[:1]
    with _memory_lock, _quiet():
        try:
            m.add(messages, user_id="drix_user", infer=infer)
        except Exception as e:
            logs.warn(f"Mem0 add failed: {e}")


def search_scored(query, limit=5, min_score=0.0):
    """Search returning the full Mem0 items (id, memory, role, score...)."""
    m = get_memory()
    if m is None:
        return []
    with _memory_lock, _quiet():
        try:
            result = m.search(query, filters={"user_id": "drix_user"}, limit=limit)
        except Exception as e:
            logs.warn(f"Mem0 search failed: {e}")
            return []
    if isinstance(result, dict):
        results = result.get("results") or []
    else:
        results = result or []
    items = [r for r in results if isinstance(r, dict) and r.get("memory")]
    if min_score > 0:
        filtered = []
        for item in items:
            try:
                score = float(item.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            if score >= min_score:
                filtered.append(item)
        items = filtered
    # Facts are compact and safe to inject; raw assistant answers are the
    # fallback while a conversation has not been consolidated yet.  User
    # messages are often old instructions and must not be re-answered.
    facts = [r for r in items if _kind_of(r) == "fact"]
    assistant = [r for r in items if _role_of(r) == "assistant" and _kind_of(r) != "fact"]
    chosen = facts[:limit]
    for item in assistant:
        if len(chosen) >= limit:
            break
        chosen.append(item)
    # Never inject raw user messages: they are often old instructions or
    # questions and the model may try to answer them again.
    return chosen


def search(query, limit=5):
    try:
        from .main import config
        min_score = float(
            config.get("memory", "inject_min_score", default=0.0) or 0.0
        )
    except Exception:
        min_score = 0.0
    return [r["memory"] for r in search_scored(query, limit, min_score)]


def get_all():
    """Backwards-compatible raw Mem0 listing (dict with a results list)."""
    m = get_memory()
    if m is None:
        return []
    with _memory_lock, _quiet():
        try:
            return m.get_all(filters={"user_id": "drix_user"})
        except Exception:
            return []


def get_all_entries(limit=500):
    """Return normalised memories: id, memory, role, kind, created_at."""
    m = get_memory()
    if m is None:
        return []
    with _memory_lock, _quiet():
        try:
            result = m.get_all(
                filters={"user_id": "drix_user"},
                top_k=max(1, int(limit)),
            )
        except Exception as e:
            logs.warn(f"Mem0 get_all failed: {e}")
            return []

    if isinstance(result, dict):
        result = result.get("results") or []
    entries = []
    for item in result or []:
        if not isinstance(item, dict):
            continue
        text = str(item.get("memory") or "").strip()
        if not text:
            continue
        entries.append({
            "id": str(item.get("id") or ""),
            "memory": text,
            "role": _role_of(item),
            "kind": _kind_of(item),
            "created_at": str(item.get("created_at") or ""),
            "metadata": dict(item.get("metadata") or {}),
        })
    return entries


def add_fact(text, metadata=None) -> bool:
    """Store one compact fact (``kind=fact``) without LLM extraction."""
    text = " ".join(str(text or "").split())
    if not text:
        return False
    m = get_memory()
    if m is None:
        return False
    meta = {"kind": "fact"}
    if metadata:
        meta.update(metadata)
    with _memory_lock, _quiet():
        try:
            result = m.add(
                [{"role": "assistant", "content": text}],
                user_id="drix_user",
                infer=False,
                metadata=meta,
            )
        except Exception as e:
            logs.warn(f"Mem0 add_fact failed: {e}")
            return False
    if isinstance(result, dict):
        return bool(result.get("results"))
    return bool(result)


def delete_many(ids) -> int:
    """Delete memories by id; returns how many were removed."""
    m = get_memory()
    if m is None:
        return 0
    deleted = 0
    with _memory_lock, _quiet():
        for memory_id in {str(i) for i in (ids or []) if i}:
            try:
                m.delete(memory_id)
                deleted += 1
            except Exception as e:
                logs.warn(f"Mem0 delete failed ({memory_id[:8]}): {e}")
    return deleted


def reset():
    global _memory, _failed_at
    with _memory_lock:
        if _memory is not None:
            try:
                _memory.reset()
            except Exception:
                pass
        _memory = None
        _failed_at = 0.0
