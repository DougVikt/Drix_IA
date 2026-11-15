# Guia de Configuração — Drix

> Como configurar a Drix de ponta a ponta: `config.yaml`, variáveis de ambiente, chaves de API,
> permissões, rede, downloads e base de conhecimento.
> Baseado em `DADOS_DEV/DRIX_COMPLETO.md`, `DADOS_DEV/medidas de segurança.md` e no estado operacional atual.

---

## Sumário

- [Visão geral e arquivos](#visão-geral-e-arquivos)
- [Como a configuração é carregada](#como-a-configuração-é-carregada)
- [Seções do `config.yaml`](#seções-do-configyaml)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Segurança e chaves](#segurança-e-chaves)
- [Rede e bloqueio SSRF](#rede-e-bloqueio-ssrf)
- [Permissões de ferramentas](#permissões-de-ferramentas)
- [Configuração pela interface web](#configuração-pela-interface-web)
- [Exemplos comuns](#exemplos-comuns)
- [Verificação e troubleshooting](#verificação-e-troubleshooting)

---

## Visão geral e arquivos

| Arquivo/pasta | Função |
|---------------|--------|
| `config/config.yaml` | Configuração principal (lida no boot e recarregada em partes) |
| `data/secrets.json` | Cofre de segredos (DPAPI no Windows, oculto) |
| `data/runtime.json` | Estado do runtime (indicador, pids, portas) |
| `data/conversations.db` | Histórico de conversas |
| `data/web_conversations.db` | Conversas da UI web |
| `data/knowledge/` | Documentos enviados para a base de conhecimento |
| `data/knowledge_db/` | Índice SQLite da base de conhecimento |
| `data/vector_db/` | Memória RAG antiga (Chroma) — não apagar |
| `data/lessons/` | Memória/aprendizagem — não apagar |
| `logs/drix.log` | Log do serviço |

## Como a configuração é carregada

1. No boot, `core/main.py` lê `config/config.yaml` e aplica:
   - **Override por env vars** para chaves sensíveis (`security.api_key` ← `DRIX_SECURITY_API_KEY`).
   - **Resolução de referências** `{env:VAR}`, `${VAR}` e `$VAR` em valores de texto.
   - **Seleção automática de modelo** por hardware, se `brain.auto_select_model` ou `local_model` estiverem ausentes.
2. Mudanças via API (`/api/settings`, `/api/providers/config`) passam por sanitização antes de salvar:
   - `security.api_key` e `operation.api_key` **nunca** são persistidos em texto plano.
   - Apenas referências `{env:...}` / `${...}` ou vazio.
3. `ConfigManager.reload()` relê o arquivo; a maioria das mudanças tem efeito imediato, algumas exigem reinício do serviço.

## Seções do `config.yaml`

### `operation` — Modo e provedor

```yaml
operation:
  mode: local              # local | api
  provider: local          # local | ollama | openai | anthropic | compatible
  api_provider: openai     # provedor quando mode=api
  model: phi3.5:3.8b
  base_url: ''             # vazio = URL padrão do provedor
  fallback_local: true     # cai para local se o provedor falhar
  temperature: 0.7
  max_tokens: 1024
  timeout: 120.0
  keep_alive: -1
  api_key: ''              # SEMPRE vazio aqui; usar env var ou cofre
```

### `brain` — Modelo e hardware

```yaml
brain:
  local_model: phi3.5:3.8b
  auto_select_model: false   # true = escolhe pelo hardware a cada start
  auto_scan: true
  installed_models: [...]
  lessons_folder: ./data/lessons
  memory_db: ./data/vector_db
  chunk_size: 1000
  model_params:
    ctx: 4096
    threads: 6
```

### `engine` — Motor Ollama

```yaml
engine:
  auto_start: true
  host: 127.0.0.1
  port: 11434
  preload: true             # pré-carrega o modelo no start
  watchdog: true
  watchdog_interval: 5
  keep_alive: -1
```

### `web` — Servidor/UI

```yaml
web:
  host: 127.0.0.1           # NÃO usar 0.0.0.0 sem HTTPS/autenticação reforçada
  port: 8000
  auto_open: true
  indicator: true
  stop_engine_on_exit: false
```

### `network` — Internet e SSRF

```yaml
network:
  allow_internet_access: true
  block_local_network: true
  allowed_domains: []        # vazio = todos (respeitando bloqueios)
  request_timeout: 15
```

### `knowledge` — Base de conhecimento (RAG)

```yaml
knowledge:
  enabled: true
  dir: ./data/knowledge
  db: ./data/knowledge_db
  max_file_mb: 50
  chunk_size: 1000
  chunk_overlap: 200          # deve ser < chunk_size
  top_k: 4
  context_chars: 1800
```

### `downloads` — Downloads de mídia

```yaml
downloads:
  enabled: true
  dir: ./workspace/downloads
  max_concurrent: 2           # 1 a 4
  ffmpeg: ''                  # vazio = imageio-ffmpeg ou PATH
  proxy: ''
  cookies: ''                 # caminho para cookies.txt
```

### `memory` — Memória e consolidação

```yaml
memory:
  infer: false
  inject_min_score: 0.6
  search_timeout: 3.5
  context_timeout: 4.0
  block_ttl_minutes: 60
  consolidate:
    enabled: true
    use_llm: true
    idle_minutes: 5
    interval_minutes: 10
    batch_size: 8
    min_entries: 8
    keep_recent: 6
    max_batches_per_run: 2
    max_tokens: 256
    retry_hours: 24
```

### `compaction`, `snapshots`, `history`, `agents`, `mcp`, `skills`, `tools`

- `compaction.enabled`, `keep_recent`, `max_tokens`, `use_llm` — compactação de contexto.
- `snapshots.enabled`, `max: 20` — snapshots de arquivos.
- `history.enabled`, `max_conversations: 50` — histórico de conversas.
- `agents.enabled`, subagentes `coder`, `researcher`, `summarizer`.
- `mcp.enabled`, `servers` — desabilitado por padrão.
- `skills.*` — skills de áudio, automação, imagem, vídeo, visão.
- `tools.enabled`, `max_steps`, `permissions` — veja seção de permissões.

## Variáveis de ambiente

| Variável | Uso | Prioridade |
|----------|-----|------------|
| `DRIX_SECURITY_API_KEY` | Chave de autenticação da API/UI | Máxima para `security.api_key` |
| `DRIX_<PROVIDER>_API_KEY` | Chave de provedor (ex.: `DRIX_OPENAI_API_KEY`) | Acima do cofre |
| `OPENAI_API_KEY` | Fallback para OpenAI | Cofre > vazio |
| `ANTHROPIC_API_KEY` | Fallback para Anthropic | Acima do cofre |
| `OLLAMA_MODELS` | Caminho dos modelos Ollama | Definida pelo launcher |

No `config.yaml` você pode referenciar env vars:

```yaml
security:
  api_key: '{env:DRIX_SECURITY_API_KEY}'
```

## Segurança e chaves

1. **Nunca** coloque `security.api_key` ou `operation.api_key` com valor real no `config.yaml` — a Drix sanitiza ao salvar, mas evite.
2. Prefira **variáveis de ambiente** para chaves que mudam por ambiente:
   ```powershell
   $env:DRIX_SECURITY_API_KEY = "gere-com-openssl-ou-python"
   $env:DRIX_OPENAI_API_KEY = "sk-..."
   ```
3. Ou use o **cofre local** (`data/secrets.json`, DPAPI no Windows, oculto): as chaves cadastradas na web (`POST /api/providers/config`) vão para o cofre, não para o YAML.
4. Para remover uma chave salva: `DELETE /api/providers/{provider}/key` (ou aba de configurações → provedores).
5. Prioridade efetiva: **env var > cofre > config legada**.
6. Segurança adicional:
   - Cookie `HttpOnly` + `SameSite=Strict`.
   - CSRF: `Sec-Fetch-Site` mesmo origem ou `Origin`/`Referer` compatível.
   - `web.host: 127.0.0.1` por padrão — para LAN, use HTTPS + auth reforçada + firewall.

## Rede e bloqueio SSRF

- `network.allow_internet_access: false` bloqueia buscas/fetch na web para todos.
- `network.block_local_network: true` impede acesso a IPs privados/loopback.
- `network.allowed_domains` — lista branca se quiser restringir.
- Toda URL passa por checagem de IP e de redirecionamentos.

## Permissões de ferramentas

Cada ferramenta tem `allow`, `ask` ou `deny` em `tools.permissions`:

| Ferramenta | Padrão atual | Observação |
|------------|--------------|------------|
| `read_file` | `allow` | Leitura |
| `write_file` | `ask` | Gravação exige confirmação |
| `run_shell` | `deny` | Desabilitado por segurança |
| `fetch_url` | `allow` | Sujeito a SSRF |
| `web_search` | `allow` | Sujeito a SSRF |
| `download_media` | `ask` | Download exige confirmação |
| `download_info/status/list/cancel` | `allow` | Metadados/controle |
| `knowledge_search` | `allow` | Busca na base local |
| `knowledge_list` | `allow` | Lista documentos |
| `snapshot_restore` | `allow` | Restauração |

Altere pela aba **Ferramentas** nas configurações ou no `config.yaml`.

## Configuração pela interface web

- **Geral:** idioma, histórico, compactação, snapshots.
- **Modelo:** provedor, modelo, temperatura, tokens, timeout, fallback, auto-select, GPU, contexto.
- **Motor:** preload, watchdog, intervalo, keep-alive.
- **Memória:** consolidação, score mínimo, timeouts.
- **Rede:** internet, bloqueio local, domínios, timeout.
- **Ferramentas:** permissões por ferramenta e limite de passos.
- **Downloads:** ativar, pasta, simultâneos, proxy, cookies, ffmpeg.
- **Conhecimento:** ativar, limites, chunk, top_k, contexto.
- **Sistema:** status, logs, runtime, parada.

Alterações via web passam por `POST /api/settings` (valida e coage valores) e `POST /api/providers/config` (salva chaves no cofre, nunca no YAML).

## Exemplos comuns

### Usar provedor OpenAI

```yaml
operation:
  mode: api
  provider: openai
  model: gpt-4o-mini
  base_url: ''
  api_key: '{env:OPENAI_API_KEY}'
```

```powershell
$env:OPENAI_API_KEY = "sk-..."
```

### Usar Ollama remoto (LAN)

```yaml
operation:
  mode: local
  provider: ollama
  base_url: http://192.168.0.50:11434
  model: llama3.2:3b
```

### Desativar internet

```yaml
network:
  allow_internet_access: false
```

### Resetar memória (cuidado)

Apague o conteúdo de `data/vector_db/` e `data/lessons/` — mas faça backup antes.
A base de conhecimento independente fica em `data/knowledge_db/`.

## Verificação e troubleshooting

```powershell
# Testar config.yaml válido
python -c "import yaml; print(yaml.safe_load(open(r'F:\config\config.yaml')))"

# Ver chaves salvas (nomes, não valores)
python -c "import sys; sys.path.insert(0,r'F:\\'); import core.secrets as s; print(s.list_secret_names())"

# Verificar portas
Test-NetConnection 127.0.0.1 -Port 8000
Test-NetConnection 127.0.0.1 -Port 11434

# Logs
Get-Content F:\logs\drix.log -Tail 30
```

| Sintoma | Causa | Solução |
|---------|-------|---------|
| 401 Unauthorized | Chave errada/ausente | Verificar `DRIX_SECURITY_API_KEY` ou cofre |
| Modelo não carrega | Porta 11434 | Reiniciar motor ou mudar `engine.port` |
| Web não abre | `web_app.py` com erro | Ver `logs/drix.log`, reiniciar serviço |
| Download falha | SSRF/rede | Liberar domínio em `allowed_domains` |
| Conhecimento vazio | Embeddings ausentes | Iniciar Ollama e puxar `nomic-embed-text` |

---

*Documento criado a partir da referência funcional da Drix em 2026-11-14.*
