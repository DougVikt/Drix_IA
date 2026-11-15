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
- [Atualizando o dump de desenvolvimento](#atualizando-o-dump-de-desenvolvimento)

---

## Pré-requisitos

- **Windows 10/11** (experiência completa) ou Linux parcial.
- **HD/SSD externo** com ao menos 8 GB livres (modelos pesados exigem muito mais).
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

```powershell
# 1. Clone ou copie o repositório para a raiz do HD externo (ex.: F:\)
git clone https://github.com/DougVikt/Drix_IA.git F:\

# 2. Crie a estrutura de diretórios esperada
cd F:\
mkdir data
mkdir workspace
mkdir logs
mkdir workspace\downloads

# 3. Crie o ambiente virtual (ou use o venv já incluído)
python -m venv .venv

# 4. Instale dependências com Poetry (recomendado) ou pip
poetry install
# ou: .venv\Scripts\pip install -r requirements.txt (se existir)

# 5. Verifique e ajuste a configuração
notepad config\config.yaml

# 6. (Opcional) Baixe o modelo local por padrão
ollama pull phi3.5:3.8b
# ou use o próprio downloader da Drix: aba Downloads / comando /baixar
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

| Item | Função |
|------|--------|
| `ia_system/engine/ollama.exe` | Motor Ollama portátil |
| `ia_system/models/` | Modelos Ollama locais |
| `ia_system/python/` | Python embarcado 3.10.11 |
| `ia_system/icon/` | Logos da UI (`logo_drix2.png`, `logo_nome_drix.png`) |
| `.venv/` | Ambiente virtual com dependências instaladas |
| `config/config.yaml` | Configuração principal (YAML) |

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
