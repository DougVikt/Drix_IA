"""Idle consolidation of old raw chat memories.

The web service stores each chat turn in Mem0 with ``infer=False``: fast, but
raw questions and answers accumulate forever.  This module waits until nobody
is chatting, asks the local model to turn old turns into compact facts, saves
those facts and only then deletes the raw entries.

It runs in a daemon thread inside the web service on purpose: the local
Qdrant store used by Mem0 cannot be opened by a second process.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import threading
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import logs, memory, providers, runtime

ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "memory_consolidation.json"

_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_start_lock = threading.Lock()
_run_lock = threading.Lock()

_SYSTEM_PROMPT = """Você organiza a memória de longo prazo da Drix.
Leia a conversa antiga e extraia apenas fatos duráveis e úteis sobre o usuário, o computador, o projeto Drix, preferências, decisões e combinados.
Regras:
- Uma informação por linha, começando com "- ".
- Cada fato deve ser curto (até 160 caracteres) e fazer sentido sozinho.
- Fatos sobre o usuário devem começar com "O usuário".
- Fatos sobre a Drix ou o projeto devem citar "Drix" ou "projeto".
- Não copie perguntas, instruções, saudações, listas de opções ou texto repetido.
- Não escreva "O usuário perguntou/mencionou"; escreva o fato diretamente.
- Não extraia definições, explicações genéricas ou conhecimento geral.
- Se a conversa for apenas uma pergunta genérica e sua explicação (ex.: "o que é RAM?", "o que é SSD?"), responda apenas: NADA
- Não invente; use apenas o que está na conversa.
- Se não houver nenhum fato útil, responda apenas: NADA
- Responda em português do Brasil.
Exemplos de fatos válidos:
- O usuário se chama Douglas.
- O usuário prefere respostas curtas.
- O notebook do usuário tem 8 GB de RAM.
- O projeto Drix usa Qdrant local para memórias.
Exemplos inválidos (se só houver isso, responda NADA):
- RAM é uma memória volátil.
- Uma impressora 3D cria objetos em camadas.
- SSD é mais rápido que HD."""

_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")
_PREFIX_RE = re.compile(r"^(?:fato|fact|mem[oó]ria|memory)\s*:\s*", re.I)
_BAD_LINE_RE = re.compile(
    r"^(?:usu[aá]rio|user|drix|assistant|conversa|contexto|pergunta)\s*:",
    re.I,
)
_QUESTION_START_RE = re.compile(
    r"^(?:pergunta|responda|explique|descreva|cite|qual|quais|quem|como|"
    r"onde|quando|por que|porque)\b",
    re.I,
)
_GENERIC_RE = re.compile(
    r"^(?:o usu[aá]rio (?:pergunt|quer saber|question|solicitou informa)|"
    r"a conversa|n[aã]o h[aá]|nenhum fato|nada a|sem fatos)",
    re.I,
)
_META_RE = re.compile(
    r"^(?:o usu[aá]rio|a usu[aá]ria)\s+"
    r"(?:(?:est[aá]|estava)\s+)?"
    r"(?:pergunt\w*|pedind\w*|querendo saber|solicitand\w*|"
    r"questionand\w*|interessad[oa] em|buscando (?:informa|saber))",
    re.I,
)
_GENERIC_FACT_RE = re.compile(
    r"^(?:drix|o drix|a drix)\s+"
    r"(?:é|são|diferencia|significa|refere-se|trata-se|consiste|representa|"
    r"funciona como|serve para)\b",
    re.I,
)
# Small local models often turn generic explanations into "facts"
# ("SSD: Disco rígido...").  Definitions are not durable user/project memory.
_DEFINITION_RE = re.compile(
    r"^(?:[^:\n]{1,40}:\s*|(?:\S+\s+){0,3}(?:é|são)\s+)"
    r"(?:um|uma|o|a|os|as)?\s*"
    r"(?:tipo|dispositivo|componente|equipamento|memória|armazenamento|"
    r"disco|teclado|monitor|processador|placa|fonte|programa|software|"
    r"hardware|assistente|sistema)\b",
    re.I,
)
# "O usuário pediu uma explicação sobre X" is a request, not a durable fact.
_REQUEST_RE = re.compile(
    r"^(?:o usu[aá]rio|a usu[aá]ria)\s+"
    r"(?:pediu|solicitou|quer|gostaria de)\s+"
    r"(?:uma\s+)?(?:explica[cç][aã]o|defini[cç][aã]o|resumo|resposta|"
    r"informa[cç][oõ]es|saber|entender|conhecer)\b",
    re.I,
)
# Keep only facts anchored in the user, the machine or the Drix project.
# Generic world knowledge ("Uma impressora 3D cria...") has no anchor.
_ANCHOR_RE = re.compile(
    r"\b(?:usu[aá]rio|usu[aá]ria|voc[eê]|seu|sua|seus|suas|meu|minha|"
    r"meus|minhas|drix|projeto|notebook|computador|"
    r"pc|m[aá]quina|windows|linux|wifi|wi-fi|roteador|pasta|arquivo|"
    r"diret[oó]rio|prefere|prefiro|prefer[eê]ncia|decidiu|escolheu|"
    r"configurou|instalou|trabalha|estuda|mora|chama)\b"
    r"|\b[A-Za-z]:\\",
    re.I,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class _ChatStarted(Exception):
    """Raised when the user starts a chat during consolidation."""


def _conf() -> dict:
    try:
        from .main import config
        raw = config.raw() or {}
    except Exception:
        raw = {}
    conf = ((raw.get("memory") or {}).get("consolidate") or {})
    try:
        return {
            "enabled": bool(conf.get("enabled", True)),
            "idle_minutes": max(0.0, float(conf.get("idle_minutes", 5) or 0)),
            "interval_minutes": max(1.0, float(conf.get("interval_minutes", 10) or 10)),
            "min_entries": max(1, int(conf.get("min_entries", 8) or 8)),
            "keep_recent": max(0, int(conf.get("keep_recent", 6) or 0)),
            "batch_size": max(1, int(conf.get("batch_size", 8) or 8)),
            "max_batches_per_run": max(1, int(conf.get("max_batches_per_run", 2) or 2)),
            "max_tokens": max(64, int(conf.get("max_tokens", 256) or 256)),
            "retry_hours": max(1.0, float(conf.get("retry_hours", 24) or 24)),
            "use_llm": bool(conf.get("use_llm", True)),
        }
    except (TypeError, ValueError):
        return {
            "enabled": True,
            "idle_minutes": 5.0,
            "interval_minutes": 10.0,
            "min_entries": 8,
            "keep_recent": 6,
            "batch_size": 8,
            "max_batches_per_run": 2,
            "max_tokens": 256,
            "retry_hours": 24.0,
            "use_llm": True,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _parse_iso(value) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0


def _empty_state() -> dict:
    return {
        "version": 1,
        "updated_at": "",
        "last_run_at": "",
        "last_success_at": "",
        "last_status": "never",
        "last_error": "",
        "last_batch": 0,
        "last_deleted": 0,
        "last_facts": [],
        "runs": 0,
        "batches": 0,
        "facts_total": 0,
        "raw_deleted_total": 0,
        "reviewed": {},
    }


def _load_state() -> dict:
    state = _empty_state()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            state.update(data)
    except Exception:
        pass
    if not isinstance(state.get("reviewed"), dict):
        state["reviewed"] = {}
    return state


def _save_state(state: dict) -> None:
    state["updated_at"] = _now_iso()
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, STATE_PATH)


def _created_key(entry: dict) -> float:
    return _parse_iso(entry.get("created_at"))


def _clean(text) -> str:
    return " ".join(str(text or "").split())


def _norm(text) -> str:
    text = unicodedata.normalize("NFKD", _clean(text).lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


def _raw_entries(entries) -> list[dict]:
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        text = _clean(entry.get("memory"))
        if len(text) < 8:
            continue
        if str(entry.get("kind") or "").lower() == "fact":
            continue
        role = str(entry.get("role") or "").lower()
        if role not in ("user", "assistant"):
            continue
        entry = dict(entry)
        entry["text"] = text
        out.append(entry)
    out.sort(key=lambda item: (_created_key(item), str(item.get("id") or "")))
    return out


def _prune_reviewed(state: dict, retry_hours: float) -> dict:
    cutoff = time.time() - max(1.0, retry_hours) * 3600.0
    reviewed = {}
    for memory_id, stamp in (state.get("reviewed") or {}).items():
        try:
            value = float(stamp)
        except (TypeError, ValueError):
            continue
        if value >= cutoff:
            reviewed[str(memory_id)] = value
    if len(reviewed) > 2000:
        newest = sorted(reviewed.items(), key=lambda pair: pair[1], reverse=True)[:2000]
        reviewed = dict(newest)
    state["reviewed"] = reviewed
    return reviewed


def _build_batch(candidates, batch_size: int, max_chars: int = 2600):
    chosen = []
    lines = []
    used = 0
    for entry in candidates:
        if len(chosen) >= batch_size:
            break
        role = "Usuário" if entry.get("role") == "user" else "Drix"
        text = entry["text"]
        if len(text) > 600:
            text = text[:597].rstrip() + "..."
        line = f"{role}: {text}"
        if chosen and (used + len(line) + 1) > max_chars:
            break
        chosen.append(entry)
        lines.append(line)
        used += len(line) + 1
    return chosen, "\n".join(lines)


def _llm_cfg(max_tokens: int) -> dict:
    try:
        from .main import config
        cfg = copy.deepcopy(config.raw() or {})
    except Exception:
        cfg = {}
    operation = cfg.setdefault("operation", {})
    operation["max_tokens"] = max(64, min(512, int(max_tokens)))
    operation["temperature"] = 0.1
    return cfg


async def _extract_llm(transcript: str, max_tokens: int,
                       known_facts=None) -> str:
    system = _SYSTEM_PROMPT
    existing = [_clean(fact)[:160] for fact in (known_facts or []) if _clean(fact)]
    if existing:
        system += (
            "\n\nFatos já conhecidos (não repita nem reformule):\n"
            + "\n".join(f"- {fact}" for fact in existing[-20:])
        )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": "Conversa:\n" + transcript + "\n\nFatos:"},
    ]
    parts = []
    length = 0
    started = time.time()

    async def _run():
        nonlocal length
        async for token in providers.stream(messages, cfg=_llm_cfg(max_tokens)):
            if runtime.chat_state().get("active", 0) > 0:
                raise _ChatStarted()
            if runtime.stopping():
                raise _ChatStarted()
            parts.append(token)
            length += len(token)
            if length >= 1600:
                break

    await asyncio.wait_for(_run(), timeout=180.0)
    return "".join(parts)


def _parse_facts(text: str, limit: int = 8) -> list[str]:
    if not text:
        return []
    text = re.sub(r"```.*?```", " ", str(text), flags=re.S)
    facts = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.upper().strip(" .:") == "NADA":
            continue
        if _BAD_LINE_RE.match(line):
            continue
        line = _BULLET_RE.sub("", line)
        line = _PREFIX_RE.sub("", line)
        line = _clean(line).strip("\"'")
        line = re.sub(r"^Ousu[aá]rio\b", "O usuário", line, flags=re.I)
        if len(line) < 10:
            continue
        if line.endswith("?"):
            continue
        if _QUESTION_START_RE.match(line):
            continue
        if _GENERIC_RE.match(line):
            continue
        if _META_RE.match(line):
            continue
        if _GENERIC_FACT_RE.match(line):
            continue
        if _DEFINITION_RE.match(line):
            continue
        if _REQUEST_RE.match(line):
            continue
        if not _ANCHOR_RE.search(line):
            continue
        if len(line) > 200:
            line = line[:197].rstrip() + "..."
        facts.append(line)
        if len(facts) >= limit:
            break
    return facts


def _heuristic_facts(batch) -> list[str]:
    """Cheap fallback: keep the first informative sentence of old answers."""
    facts = []
    for entry in batch:
        if entry.get("role") != "assistant":
            continue
        text = re.sub(r"```.*?```", " ", entry["text"], flags=re.S)
        text = text.split("\n\n---")[0]
        picked = ""
        for sentence in _SENTENCE_RE.split(text):
            sentence = _clean(sentence)
            if len(sentence) < 15 or sentence.endswith("?"):
                continue
            if _DEFINITION_RE.match(sentence):
                continue
            if not _ANCHOR_RE.search(sentence):
                continue
            if picked and len(picked) + len(sentence) + 1 > 180:
                break
            picked = (picked + " " + sentence).strip()
            if len(picked) >= 80:
                break
        if picked:
            facts.append(picked[:180])
    return facts


def _dedupe_facts(facts, known_keys) -> list[str]:
    def tokens(key):
        return {token for token in key.split() if len(token) > 2}

    def similar(left, right):
        a, b = tokens(left), tokens(right)
        if not a or not b:
            return False
        common = len(a & b)
        return common >= 3 and common / min(len(a), len(b)) >= 0.7

    out = []
    for fact in facts:
        key = _norm(fact)
        if not key or key in known_keys:
            continue
        if any(similar(key, other) for other in known_keys):
            continue
        known_keys.add(key)
        out.append(fact)
    return out


def _reviewed_batch(state: dict, batch, status: str) -> None:
    now = time.time()
    for entry in batch:
        memory_id = str(entry.get("id") or "")
        if memory_id:
            state["reviewed"][memory_id] = now
    state["last_status"] = status
    state["last_run_at"] = _now_iso()
    state["last_batch"] = len(batch)
    state["last_deleted"] = 0


def run_once(force: bool = False) -> dict:
    """Run one consolidation cycle.  Never runs while a chat is active."""
    if not _run_lock.acquire(blocking=False):
        return {"status": "busy"}
    try:
        conf = _conf()
        if not force and not conf["enabled"]:
            return {"status": "disabled"}
        if runtime.stopping():
            return {"status": "stopping"}
        chat = runtime.chat_state()
        if chat.get("active", 0) > 0:
            return {"status": "chat_active"}

        engine = runtime.engine_status()
        if not engine.get("engine_running"):
            state = _load_state()
            state["last_run_at"] = _now_iso()
            state["last_status"] = "engine_off"
            _save_state(state)
            return {"status": "engine_off"}

        entries = memory.get_all_entries(limit=500)
        if not entries:
            state = _load_state()
            state["last_run_at"] = _now_iso()
            state["last_status"] = "empty"
            _save_state(state)
            return {"status": "empty"}

        state = _load_state()
        reviewed = _prune_reviewed(state, conf["retry_hours"])
        raw = _raw_entries(entries)
        keep_recent = conf["keep_recent"]
        older = raw[:-keep_recent] if keep_recent else raw
        candidates = [
            entry for entry in older
            if str(entry.get("id") or "") not in reviewed
        ]

        if not force and len(candidates) < conf["min_entries"]:
            state["last_run_at"] = _now_iso()
            state["last_status"] = "not_enough"
            _save_state(state)
            return {
                "status": "not_enough",
                "candidates": len(candidates),
                "raw": len(raw),
            }
        if not candidates:
            state["last_run_at"] = _now_iso()
            state["last_status"] = "nothing_to_do"
            _save_state(state)
            return {"status": "nothing_to_do", "raw": len(raw)}

        known_keys = {
            _norm(entry.get("memory"))
            for entry in entries
            if str(entry.get("kind") or "").lower() == "fact"
        }
        known_facts = [
            entry.get("memory")
            for entry in entries
            if str(entry.get("kind") or "").lower() == "fact"
        ]
        total_facts = 0
        total_deleted = 0
        batches = 0
        last_status = ""

        for _ in range(conf["max_batches_per_run"]):
            if runtime.chat_state().get("active", 0) > 0:
                last_status = "chat_active"
                break
            batch, transcript = _build_batch(
                candidates, conf["batch_size"]
            )
            if not batch:
                break
            candidates = candidates[len(batch):]

            facts = []
            used_llm = False
            llm_ok = False
            if conf["use_llm"]:
                try:
                    answer = asyncio.run(
                        _extract_llm(
                            transcript, conf["max_tokens"], known_facts
                        )
                    )
                    llm_ok = True
                    facts = _parse_facts(answer, limit=3)
                    used_llm = bool(facts)
                except _ChatStarted:
                    last_status = "chat_started"
                    break
                except Exception as exc:
                    logs.warn(f"Memory consolidation LLM failed: {exc}")

            if not facts and not llm_ok:
                facts = _heuristic_facts(batch)
                if facts:
                    logs.info("Memory consolidation used heuristic fallback")

            facts = _dedupe_facts(facts, known_keys)
            if not facts:
                _reviewed_batch(state, batch, "no_facts")
                _save_state(state)
                batches += 1
                last_status = "no_facts"
                continue

            source = "llm" if used_llm else "heuristic"
            saved = 0
            for fact in facts:
                if memory.add_fact(fact, {"source": source}):
                    saved += 1
                    known_keys.add(_norm(fact))
                    known_facts.append(fact)
            if saved == 0:
                _reviewed_batch(state, batch, "save_failed")
                _save_state(state)
                batches += 1
                last_status = "save_failed"
                continue

            deleted = memory.delete_many([entry.get("id") for entry in batch])
            total_facts += saved
            total_deleted += deleted
            batches += 1

            state["facts_total"] = int(state.get("facts_total", 0)) + saved
            state["raw_deleted_total"] = (
                int(state.get("raw_deleted_total", 0)) + deleted
            )
            state["runs"] = int(state.get("runs", 0)) + 1
            state["batches"] = int(state.get("batches", 0)) + 1
            state["last_facts"] = facts[:8]
            state["last_deleted"] = deleted
            state["last_batch"] = len(batch)
            state["last_status"] = "ok"
            state["last_run_at"] = _now_iso()
            state["last_success_at"] = _now_iso()
            state["last_error"] = ""
            _save_state(state)
            # New facts are available: refresh the per-workspace memory block
            # so the next chat does not inject a deleted raw answer.
            try:
                from .main import _invalidate_memory_cache
                _invalidate_memory_cache()
            except Exception:
                pass
            last_status = "ok"

        state["last_run_at"] = _now_iso()
        if last_status in ("no_facts", "save_failed"):
            state["last_status"] = last_status
        _save_state(state)
        return {
            "status": last_status or "idle",
            "batches": batches,
            "facts": total_facts,
            "deleted": total_deleted,
            "raw": len(raw),
        }
    except Exception as exc:
        logs.warn(f"Memory consolidation failed: {exc}")
        state = _load_state()
        state["last_status"] = "error"
        state["last_error"] = str(exc)
        state["last_run_at"] = _now_iso()
        try:
            _save_state(state)
        except Exception:
            pass
        return {"status": "error", "error": str(exc)}
    finally:
        _run_lock.release()


def _loop() -> None:
    last_attempt = 0.0
    while not _stop.is_set():
        try:
            if _wake.is_set():
                _wake.clear()
                if runtime.stopping():
                    break
                if runtime.chat_state().get("active", 0) > 0:
                    logs.info("Memory consolidation postponed: chat active")
                else:
                    result = run_once(force=True)
                    logs.info(f"Memory consolidation (manual): {result}")
                    last_attempt = time.time()
            else:
                conf = _conf()
                if conf["enabled"] and not runtime.stopping():
                    state = _load_state()
                    last_run = _parse_iso(state.get("last_run_at"))
                    interval = conf["interval_minutes"] * 60.0
                    chat = runtime.chat_state()
                    idle_ok = (
                        chat.get("active", 0) == 0
                        and chat.get("idle_seconds", 0.0)
                        >= conf["idle_minutes"] * 60.0
                    )
                    due = (not last_run or time.time() - last_run >= interval)
                    if idle_ok and due and time.time() - last_attempt >= interval:
                        result = run_once()
                        last_attempt = time.time()
                        if result.get("status") not in (
                            "empty", "nothing_to_do", "not_enough", "disabled"
                        ):
                            logs.info(f"Memory consolidation: {result}")
        except Exception as exc:
            logs.warn(f"Memory consolidation loop: {exc}")

        # Stay responsive to manual requests and to a stop without busy-looping.
        for _ in range(15):
            if _stop.wait(1.0) or _wake.is_set():
                break


def start() -> None:
    global _thread
    with _start_lock:
        if _thread is not None and _thread.is_alive():
            return
        _stop.clear()
        _thread = threading.Thread(
            target=_loop, daemon=True, name="drix-memory-maintenance"
        )
        _thread.start()


def stop() -> None:
    _stop.set()
    _wake.set()


def request_now(force: bool = False) -> dict:
    if runtime.stopping():
        return {"started": False, "reason": "stopping"}
    chat = runtime.chat_state()
    if chat.get("active", 0) > 0:
        return {"started": False, "reason": "chat_active"}
    conf = _conf()
    if not conf["enabled"] and not force:
        return {"started": False, "reason": "disabled"}
    _wake.set()
    return {"started": True}


def status() -> dict:
    conf = _conf()
    state = _load_state()
    entries = memory.get_all_entries(limit=500)
    facts = sum(1 for entry in entries if str(entry.get("kind")) == "fact")
    return {
        "config": conf,
        "state": state,
        "chat": runtime.chat_state(),
        "entries": {
            "total": len(entries),
            "facts": facts,
            "raw": len(entries) - facts,
        },
        "thread_alive": bool(_thread is not None and _thread.is_alive()),
    }
