# data/ — Drix runtime data

This folder is created and managed by the application at runtime.
**Do not edit, version or delete** without a backup.

## What is in here

| Path | Content | Essential to run? |
|------|---------|-------------------|
| `secrets.json` | API key vault (DPAPI on Windows, hidden) | No — created on first start |
| `conversations.db` | Conversation history (terminal) | No — created automatically |
| `web_conversations.db` | Conversation history (web) | No — created automatically |
| `runtime.json` | Runtime state (pids, ports, components) | No — created automatically |
| `hardware_cache.json` | Hardware analysis cache | No — created automatically |
| `memory_consolidation.json` | Memory consolidation state | No — created automatically |
| `knowledge/` | Documents uploaded to the knowledge base | No — created on first upload |
| `knowledge_db/` | Knowledge base SQLite index | No — created on first indexing |
| `vector_db/` | Legacy RAG memory (Chroma) | No — created automatically |
| `lessons/` | Consolidated learnings | No — created automatically |
| `snapshots/` | File snapshots | No — created automatically |
| `stopping.flag` | Safe-stop flag | No — transient |

## Rules

- `data/` is **not versioned** (except this README): it is local state of the portable drive.
- To migrate to another PC, copy only `data/lessons/`, `data/knowledge/` and
  `data/secrets.json` (the latter depends on the Windows user's DPAPI).
- Never upload `secrets.json` to public repositories.
- To reset everything: stop Drix, delete the contents of `data/` and start again.

> If this folder does not exist, Drix creates it automatically on the first `start.bat`.
