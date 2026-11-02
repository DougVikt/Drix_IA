import os
import time
from pathlib import Path
from . import logs

HD_ROOT = Path(__file__).resolve().parent.parent
MEM0_DIR = HD_ROOT / "data" / "mem0"
_memory = None
_failed_at = 0.0
_RETRY_SECONDS = 300


def _get_model():
    from . import hardware
    hw = hardware.analyze()
    return hw.get("selected_model", "phi3.5:3.8b")


def get_memory():
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
    import sys
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


def add(conversation_turn):
    m = get_memory()
    if m is None:
        return
    messages = [
        {"role": "user", "content": conversation_turn["user"]},
        {"role": "assistant", "content": conversation_turn["assistant"]},
    ]
    import sys
    _se = sys.stderr
    sys.stderr = None
    try:
        m.add(messages, user_id="drix_user")
    except Exception as e:
        logs.warn(f"Mem0 add failed: {e}")
    finally:
        sys.stderr = _se


def search(query, limit=5):
    m = get_memory()
    if m is None:
        return []
    import sys
    _se = sys.stderr
    sys.stderr = None
    try:
        results = m.search(query, filters={"user_id": "drix_user"}, limit=limit)
        return [r["memory"] for r in results if "memory" in r]
    except Exception as e:
        logs.warn(f"Mem0 search failed: {e}")
        return []
    finally:
        sys.stderr = _se


def get_all():
    m = get_memory()
    if m is None:
        return []
    import sys
    _se = sys.stderr
    sys.stderr = None
    try:
        return m.get_all(filters={"user_id": "drix_user"})
    except Exception:
        return []
    finally:
        sys.stderr = _se


def reset():
    global _memory, _failed_at
    if _memory is not None:
        try:
            _memory.reset()
        except Exception:
            pass
    _memory = None
    _failed_at = 0.0
