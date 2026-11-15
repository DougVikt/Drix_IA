# data/ — Dados de runtime da Drix

Esta pasta é criada e gerida pela aplicação em tempo de execução.
**Não edite, não versione e não apague** sem backup.

## O que tem aqui

| Caminho | Conteúdo | Essencial para executar? |
|---------|----------|---------------------------|
| `secrets.json` | Cofre de chaves de API (DPAPI no Windows, oculto) | Não — gerado no primeiro start |
| `conversations.db` | Histórico de conversas (terminal) | Não — gerado automaticamente |
| `web_conversations.db` | Histórico de conversas (web) | Não — gerado automaticamente |
| `runtime.json` | Estado do runtime (pids, portas, componentes) | Não — gerado automaticamente |
| `hardware_cache.json` | Cache de análise de hardware | Não — gerado automaticamente |
| `memory_consolidation.json` | Estado da consolidação de memória | Não — gerado automaticamente |
| `knowledge/` | Documentos enviados para a base de conhecimento | Não — criado no primeiro upload |
| `knowledge_db/` | Índice SQLite da base de conhecimento | Não — criado na primeira indexação |
| `vector_db/` | Memória RAG antiga (Chroma) | Não — criado automaticamente (ignorado pelo git) |
| `lessons/` | Aprendizados consolidados | Não — criado automaticamente |
| `snapshots/` | Snapshots de arquivos | Não — criado automaticamente |
| `stopping.flag` | Sinalização de parada segura | Não — transiente |

## Regras

- `data/` **não é versionado** (exceto este README): é estado local do HD portátil.
- Para migrar para outro PC, copie apenas `data/lessons/`, `data/knowledge/` e
  `data/secrets.json` (este último depende de DPAPI do usuário Windows).
- Nunca suba `secrets.json` para repositórios públicos.
- Para resetar tudo: pare a Drix, apague o conteúdo de `data/` e inicie novamente.

> Se esta pasta não existir, a Drix cria automaticamente no primeiro `start.bat`.
