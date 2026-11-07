"""Context compaction for long conversations.

When a workspace grows past ``compaction.max_tokens`` the oldest messages are
summarised by the active provider and replaced by a short summary stored in the
conversation database.  The most recent ``keep_recent`` messages are always
kept verbatim in the prompt.
"""

from __future__ import annotations

from typing import Any

from . import logs, providers

_SUMMARY_PROMPT = (
    "Resuma a conversa abaixo em português, em no máximo 12 linhas. "
    "Preserve decisões, nomes, caminhos de arquivo, comandos e pendências. "
    "Não invente informação. Responda apenas com o resumo."
)


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def _cfg(cfg: dict | None) -> dict:
    if cfg is not None:
        return cfg
    try:
        from .main import config as main_config
        return main_config.raw()
    except Exception:
        return {}


def _heuristic_summary(transcript: str, limit: int = 1500) -> str:
    lines = [line.strip() for line in transcript.splitlines() if line.strip()]
    if not lines:
        return "(conversa vazia)"
    if len(lines) <= 12:
        text = "\n".join(lines)
    else:
        text = "\n".join(lines[:6] + ["..."] + lines[-6:])
    if len(text) > limit:
        text = text[:limit] + "\n[resumo truncado]"
    return text


async def _summarize(transcript: str) -> str:
    conf = _cfg(None).get("compaction") or {}
    if not conf.get("use_llm", True):
        # Local CPU generation is the bottleneck; a heuristic summary is
        # instant and avoids adding another full model call before a reply.
        return _heuristic_summary(transcript)
    messages = [
        {"role": "system", "content": _SUMMARY_PROMPT},
        {"role": "user", "content": transcript[:12000]},
    ]
    try:
        summary = await providers.complete(messages)
        summary = (summary or "").strip()
        if summary:
            return summary
    except Exception as exc:
        logs.warn(f"Compaction summarization failed: {exc}")
    return _heuristic_summary(transcript)


async def maybe_compact(conv_mgr, workspace: str | None, cfg: dict | None = None,
                        force: bool = False) -> dict[str, Any] | None:
    """Compact the workspace history if it is over the configured budget."""
    if not conv_mgr or not workspace:
        return None

    conf = _cfg(cfg).get("compaction") or {}
    if not conf.get("enabled", True):
        return None

    try:
        max_tokens = int(conf.get("max_tokens", 3000))
        keep_recent = max(1, int(conf.get("keep_recent", 10)))
    except (TypeError, ValueError):
        max_tokens, keep_recent = 3000, 10

    previous = conv_mgr.get_summary(workspace)
    already_covered = 0
    if previous:
        try:
            already_covered = int(previous.get("covered_until") or 0)
        except (TypeError, ValueError):
            already_covered = 0

    rows = conv_mgr.get_all_history_for(workspace)
    # Only consider messages that are not in the stored summary yet;
    # otherwise every turn re-summarises the whole workspace and the
    # summary keeps growing.
    rows = [r for r in rows if int(r[0]) > already_covered]
    if not rows:
        return None

    total = sum(estimate_tokens(row[2]) for row in rows)
    if not force and total <= max_tokens:
        return None
    if len(rows) <= keep_recent:
        return None

    old_rows = rows[:-keep_recent]
    if not old_rows:
        return None
    covered_until = old_rows[-1][0]

    transcript_parts = []
    if previous and previous.get("summary"):
        transcript_parts.append("Resumo anterior:\n" + previous["summary"])
    transcript_parts.append(
        "\n".join(f"{role}: {content}" for _mid, role, content in old_rows)
    )
    transcript = "\n\n".join(transcript_parts)

    summary = await _summarize(transcript)
    conv_mgr.set_summary(workspace, summary, covered_until)
    logs.info(
        f"Compacted {len(old_rows)} message(s) of workspace '{workspace}' "
        f"({total} estimated tokens)"
    )
    return {
        "workspace": workspace,
        "messages_compacted": len(old_rows),
        "covered_until": covered_until,
        "estimated_tokens_before": total,
        "summary": summary,
    }


def prompt_section(conv_mgr, workspace: str | None) -> str:
    if not conv_mgr or not workspace:
        return ""
    try:
        stored = conv_mgr.get_summary(workspace)
    except Exception:
        return ""
    if not stored or not stored.get("summary"):
        return ""
    return "Resumo das mensagens anteriores:\n" + stored["summary"]
