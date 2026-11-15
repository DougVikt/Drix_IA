# Drix — IA Portátil

![nome drix](ia_system/icon/logo_nome_drix.png)

> **Versão:** `0.1.0-alpha` · **Licença:** MIT · **Status:** funcional, em desenvolvimento ativo

Assistente de IA **portátil**: roda direto de um HD/SSD externo, sem instalar nada no PC hospedeiro.
Motor Ollama embarcado, interface web leve, modo terminal e headless, memória persistente,
agentes, downloads por URL e base de conhecimento local (RAG).

---

## Sumário

- [O que é](#o-que-é)
- [Recursos](#recursos)
- [Início rápido](#início-rápido)
- [Documentação](#documentação)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Segurança](#segurança)
- [Licença](#licença)

---

## O que é

A Drix foi criada para ser **independente do PC hospedeiro**: tudo o que ela precisa fica na
pasta raiz do disco portátil — Python embarcado, Ollama, modelos, dados e configuração.

- **Modo local por padrão:** modelos rodam no motor embarcado (`ia_system/`), sem internet.
- **Provedores online opcionais:** OpenAI, Anthropic e qualquer endpoint OpenAI-compatible.
- **Privacidade:** chaves de API ficam em cofre local (DPAPI no Windows) e/ou variáveis de
  ambiente — nunca em texto plano no `config.yaml`.

## Recursos

| Área | O que faz |
|------|-----------|
| Chat | Streaming SSE, histórico por workspace, anexos, tema claro/escuro |
| Modelos | Seleção por hardware, troca otimizada, pré-carregamento em background |
| Agentes | Tool calling com permissões, subagentes (`coder`, `researcher`, `summarizer`) |
| Memória | SQLite + Chroma, consolidação em segundo plano, compactação de contexto |
| Web | Busca/fetch com política de rede e bloqueio SSRF, conteúdo tratado como não confiável |
| Downloads | yt-dlp + ffmpeg portátil: vídeo/áudio por URL, fila, progresso e cancelamento |
| Conhecimento | RAG local em SQLite: upload de PDF/DOCX/TXT/…, busca semântica, fontes citadas no chat |
| Ferramentas | Shell, arquivos, memória, snapshots, MCP, skills (áudio, imagem, vídeo, visão) |

## Início rápido

```powershell
# 1. Conecte o HD/SSD externo como F:
# 2. Execute o launcher
F:\start.bat

# 3. Escolha o modo: web, terminal ou headless
# 4. No modo web, o navegador abre em http://127.0.0.1:8000
```

Para parar, use **Parar tudo** no painel de serviços (indicador). Nunca feche a janela do
indicador pelo X — o fechamento está desabilitado de propósito para forçar a parada segura.

Verificação rápida:

```powershell
Test-NetConnection 127.0.0.1 -Port 8000   # API/web
Test-NetConnection 127.0.0.1 -Port 11434  # Ollama
```

## Documentação

Os guias detalhados ficam em [`docs/`](./docs), separados para o README não ficar enorme:

| Documento | Use quando quiser... |
|-----------|----------------------|
| [`docs/CRIACAO.md`](./docs/CRIACAO.md) | Entender como a Drix é montada, recriar o ambiente do zero, estrutura de pastas e builds |
| [`docs/CONFIGURACAO.md`](./docs/CONFIGURACAO.md) | Configurar tudo: `config.yaml`, variáveis de ambiente, chaves de API, permissões, rede |
| [`DADOS_DEV/`](./DADOS_DEV/) | Documentação de desenvolvimento (histórico, referência completa, status) — **local, não versionada** |

## Estrutura do projeto

```
F:\
├── api/            # FastAPI: auth, engine, rotas REST
├── client/         # Cliente Drix (terminal/API)
├── config/         # config.yaml (configuração principal)
├── core/           # Núcleo: agent, providers, tools, memory, downloader, knowledge...
├── data/           # Dados persistentes (conversas, memórias, secrets, knowledge)
├── docs/           # Guias do usuário (criação e configuração)
├── ia_system/      # Ollama portátil + modelos + Python embarcado
├── logs/           # drx.log / all.log
├── scripts/        # start.py, service.py, indicator.py, update_dump.py
├── skills/         # Skills instaladas
├── tests/          # Testes (unittest)
├── ui/             # Interface web (front) + web_app.py
├── workspace/      # Área de trabalho; downloads/ por padrão
├── .venv/          # Ambiente virtual
├── Makefile
├── pyproject.toml  # Poetry · versão 0.1.0-alpha
└── start.bat       # Launcher
```

## Segurança

- Autenticação por API key + cookie `HttpOnly`/`SameSite=Strict`; CSRF por mesma origem.
- Rate limit (60 req/min geral, 30 req/min chat); polling isento de cota.
- SSRF: bloqueio de IPs privados/loopback e lista de domínios permitidos.
- Segredos em `data/secrets.json` (DPAPI, oculto no Windows) ou env vars
  (`DRIX_SECURITY_API_KEY`, `DRIX_<PROVIDER>_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`).
- Conteúdo web e trechos de conhecimento são tratados como **não confiáveis** nos prompts.
- Detalhes em [`docs/CONFIGURACAO.md`](./docs/CONFIGURACAO.md#segurança-e-chaves).

## Licença

MIT — veja [`LICENSE`](./LICENSE).
