# Guia de Criação — Drix

> Como a Drix é montada, como recriar o ambiente do zero e como empacotá-la em um HD/SSD portátil.
> Baseado em `DADOS_DEV/HISTORICO_DESENVOLVIMENTO.md` e `DADOS_DEV/STATUS_ATUAL.md`.

---

## Sumário

- [Pré-requisitos](#pré-requisitos)
- [Como a Drix é empacotada](#como-a-drix-é-empacotada)
- [Montando o ambiente do zero](#montando-o-ambiente-do-zero)
- [Estrutura de pastas](#estrutura-de-pastas)
- [Submódulos e arquivos embarcado](#submódulos-e-arquivos-embarcados)
- [Iniciando pela primeira vez](#iniciando-pela-primeira-vez)
- [Desenvolvimento e builds](#desenvolvimento-e-builds)
- [Problemas comuns na criação](#problemas-comuns-na-criacao)

---

## Pré-requisitos

- **Windows 10/11** (experiência completa) ou Linux parcial.
- **HD/SSD externo** com ao menos 30 GB livres (modelos pesados exigem muito mais).
- **Python 3.10+** (o ambiente embarcado usa Python 3.10.11).
- **Git** (opcional no HD portátil, necessário para contribuir).
- **Navegador** moderno (Chrome, Firefox, Edge).
- **Sem internet** funciona por padrão no modo local.

## Como a Drix é empacotada

A Drix é um **launcher autossuficiente**: tudo o que ela precisa está na pasta raiz.

1. `start.bat` define o `PATH` para `ia_system\python`, `ia_system\bin` e `ia_system\engine`, e a variável `OLLAMA_MODELS` para `ia_system\models`.
2. `core/checker.py` chama `scripts/service.py`, que escolhe o modo (`web`, `terminal`, `headless`).
3. O modo `web` inicia o serviço na porta `8000` e só abre o navegador quando o servidor responde.
4. O indicador (`scripts/indicator.py`) fica como bandeja/status com a opção **Parar tudo**.
5. Defina `OLLAMA_MODELS` na pasta `ia_system\models` para que o Ollama encontre os modelos localmente.

## Montando o ambiente do zero

O repositório (git) contém **só o código, a configuração e os ícones**. Os componentes
binários são grandes demais para o git e são obtidos à parte:

| Componente | Tamanho aprox. | Como obter |
|------------|----------------|------------|
| `.venv/` | 1,1 GB | `poetry install` (ou `pip install` do `pyproject.toml`) |
| `ia_system/python/` | ~265 MB | **WinPython 3.10.11** portátil, extraído para `ia_system\python\` |
| `ia_system/engine/` | ~1,85 GB | **Ollama** portátil: copiar `ollama.exe` + DLLs para `ia_system\engine\` |
| `ia_system/models/` | 21 GB+ | `ollama pull` com `OLLAMA_MODELS` apontado para cá |
| `ia_system/bin/` | ~1 GB | ferramentas GNU (make.exe, libiconv/libintl) |
| `ia_system/poetry_cache/` | ~573 MB | opcional; cache do Poetry para instalação offline |

```powershell
# 1. Clone ou copie o repositório para a raiz do HD externo (ex.: F:\)
git clone https://github.com/DougVikt/Drix_IA.git F:\

# 2. Coloque os componentes portáteis (WinPython + Ollama) em ia_system\
#    (copie de outro HD da Drix ou baixe os fontes oficiais)

# 3. Crie o ambiente virtual e instale dependências
python -m venv .venv
poetry install

# 4. Baixe o modelo local padrão (OLLAMA_MODELS já é definido pelo start.bat)
F:\start.bat                       # inicia o motor Ollama embarcado
.venv\Scripts\python.exe -c "import subprocess; print(subprocess.run(['F:\ia_system\engine\ollama.exe','pull','phi3.5:3.8b']).returncode)"

# 5. Verifique e ajuste a configuração
notepad config\config.yaml

# 6. (Opcional) Base de conhecimento e downloads usam pastas em data/ e workspace/,
#    criadas automaticamente no primeiro start.
```

> **Essencial para executar:** `start.bat`, `pyproject.toml` + `poetry.lock`,
> `config/config.yaml`, `ia_system/icon/*.png` (versão no git) e os componentes
> binários da tabela acima. Tudo em `data/` é criado automaticamente no primeiro
> start — veja [`data/README.md`](../data/README.md).

```powershell
# Verificação rápida de que tudo subiu
Test-NetConnection 127.0.0.1 -Port 8000   # API/web
Test-NetConnection 127.0.0.1 -Port 11434  # Ollama
Get-Content F:\logs\drix.log -Tail 20     # log do serviço
```

## Estrutura de pastas

```
F:\
├── api/            # API REST (FastAPI): /model, /providers, /chat, /downloads, /knowledge...
├── config/         # config.yaml — configuração principal
├── core/           # Núcleo: agent, providers, memory, tools, downloader, knowledge, runtime...
├── data/           # Dados persistentes: conversas, memórias, secrets.json, knowledge_db...
├── docs/           # Guias do usuário (este arquivo e CONFIGURACAO.md)
├── ia_system/      # Ollama portátil (engine), modelos, Python embarcado, ícones
├── logs/           # drx.log / all.log
├── scripts/        # start.py, service.py, indicator.py, update_dump.py
├── skills/         # Skills (áudio, automação, imagem, vídeo, visão)
├── tests/          # Suíte de testes unittest
├── ui/             # Front (HTML/CSS/JS) + web_app.py (FastAPI)
├── workspace/      # Área de trabalho; downloads por padrão em workspace/downloads
├── .venv/          # Ambiente virtual
├── Makefile
├── pyproject.toml  # Poetry
└── start.bat       # Launcher
```

## Submódulos e arquivos embarcados

| Item | Função | Versionado? |
|------|--------|-------------|
| `ia_system/engine/ollama.exe` | Motor Ollama portátil | Não — reobter à parte |
| `ia_system/models/` | Modelos Ollama locais | Não — `ollama pull` |
| `ia_system/python/` | Python embarcado 3.10.11 (WinPython) | Não — reobter à parte |
| `ia_system/bin/` | Ferramentas GNU (make, iconv) | Não — reobter à parte |
| `ia_system/icon/` | Logos da UI (`logo_drix2.png`, `logo_nome_drix.png`) | **Sim** (exceção no `.gitignore`) |
| `.venv/` | Ambiente virtual com dependências instaladas | Não — `poetry install` |
| `config/config.yaml` | Configuração principal (YAML) | **Sim** |
| `data/` | Dados de runtime (conversas, memórias, secrets) | Não — criado em runtime |

> O `DADOS_DEV/` é a documentação de desenvolvimento; não é sensível, apenas não versionado por decisão de projeto.

## Iniciando pela primeira vez

```powershell
F:\start.bat
```

Saída esperada (resumida):

1. `core/checker.py` verifica se o ambiente está ok.
2. `scripts/service.py` pergunta/inicia o modo.
3. No modo `web`, abre `http://127.0.0.1:8000`.
4. O indicador aparece na bandeja/Barra de Status.

## Desenvolvimento e builds

```powershell
# Rodar testes
python -m unittest discover -s tests -v

# Compilar todos os módulos para checar sintaxe
python -m py_compile $(Get-ChildItem -Recurse -Filter *.py | Select-Object -ExpandProperty FullName)

# Atualizar dependências no venv
poetry lock && poetry install

# Makefile (no Linux/WSL ou com make disponível)
make test
```

Checklist antes de commitar:

1. `python -m py_compile` em todos os módulos alterados.
2. `python -m unittest` (quando disponível).
3. Verificar `git status` — nada de `data/`, `logs/`, `workspace/` ou `DADOS_DEV/` commitado.
4. Se alterar segredos, nunca versionar `config/config.yaml` com chaves em texto plano.
5. Atualizar este guia se a estrutura ou os pré-requisitos mudarem.


## Problemas comuns na criação

| Sintoma | Causa provável | Solução |
|---------|----------------|---------|
| `start.bat` abre e fecha | Python embarcado ausente ou corrompido | Verificar `ia_system/python/` |
| Ollama não inicia | Porta 11434 ocupada | Fechar Ollama externo ou mudar porta |
| UI não carrega | `web_app.py` com erro de importação | Verificar logs em `logs/drix.log` |
| Modelo não pré-carrega | Modelo não baixado | `F:\start.bat` → modo web → trocar modelo |
| Download falha | yt-dlp desatualizado | `pyproject.toml` + atualizar venv |

---

*Documento criado a partir do estado operacional e da referência funcional da Drix em 2026-11-14.*
