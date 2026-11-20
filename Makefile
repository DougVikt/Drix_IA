# Identifica o comando principal e os argumentos
COMMAND    := $(firstword $(MAKECMDGOALS))
ARG := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))

# Silencia os argumentos para o Make 3.81 nao tentar executa-los
ifneq ($(strip $(ARG)),)
$(eval $(ARG):;@:)
endif

# Variaveis por plataforma
ifeq ($(OS),Windows_NT)
  PYTHON = .venv\\Scripts\\python.exe
  OLLAMA = ./ia_system/engine/ollama.exe
  SHELL = cmd.exe   # Necessario para make.exe do GnuWin32 no Windows
  START = start.bat
else
  PYTHON = .venv/bin/python
  OLLAMA = ./ia_system/engine/ollama
  SHELL = /bin/sh
  START = bash start.sh
endif

.PHONY: help install start add remove info up run web ui learn shell clean setup-media backup logs status sync dump ollama self-test test

help:
	@echo "Comandos disponiveis para IA Portatil:"
	@echo "  make install     	- Instala dependencias via Poetry"
	@echo "  make start       	- Inicia a Drix (start.bat ou start.sh)"
	@echo "  make add ARG   	- Adiciona dependencias via Poetry"
	@echo "  make remove ARG	- Remove dependencias via Poetry"
	@echo "  make info ARG		- Lista versoes das dependencias(ARG para especifico)"
	@echo "  make up			- Atualiza dependencias contidas no Poetry"
	@echo "  make run         	- Inicia a IA em modo chat (terminal)"
	@echo "  make web         	- Inicia interface web (FastAPI)"
	@echo "  make ui          	- Inicia a interface grafica (CustomTkinter)"
	@echo "  make learn       	- Forca atualizacao do aprendizado (RAG)"
	@echo "  make backup      	- Faz backup do banco vetorial"
	@echo "  make logs        	- Mostra os logs da sessao atual"
	@echo "  make sync       	- Sincroniza config, modelos, skills e dump"
	@echo "  make status      	- Mostra status do sistema"
	@echo "  make shell       	- Abre terminal do Poetry no HD"
	@echo "  make clean       	- Limpa caches e .venv"
	@echo "  make dump        	- Atualiza o dump cumulativo da Drix"
	@echo "  make setup-media 	- Baixa modelos de imagem/audio"
	@echo "  make self-test   	- Diagnostico de inicializacao"

add:
	@echo Adicionando dependencia....
	poetry add $(ARG)

remove:
	@echo Removendo dependencia...
	poetry remove $(ARG)

info:
	poetry show $(ARG)

install:
	poetry install

start:
	$(START)

run:
	$(PYTHON) -m core.main --interface

web:
	$(PYTHON) -m ui.web_app

ui:
	$(PYTHON) -m ui.app

learn:
	$(PYTHON) -m core.main --update-db

dump:
	$(PYTHON) scripts/update_dump.py "Manual dump update"

backup:
	$(PYTHON) scripts/backup.py

logs:
ifeq ($(OS),Windows_NT)
	@if exist logs\drix.log type logs\drix.log
else
	@tail -n 100 logs/drix.log 2>/dev/null || true
endif

sync:
	$(PYTHON) -m core.config_auto

status:
	$(PYTHON) scripts/status.py

shell:
	poetry shell $(ARG)

up:
	poetry update $(ARG)

clean:
ifeq ($(OS),Windows_NT)
	@if exist .venv rmdir /s /q .venv
	@if exist ia_system\poetry_cache rmdir /s /q ia_system\poetry_cache
	@if exist __pycache__ rmdir /s /q __pycache__
	@echo "Caches limpos."
else
	@rm -rf .venv ia_system/poetry_cache __pycache__
	@echo "Caches limpos."
endif

setup-media:
	$(PYTHON) scripts/download_media_models.py

self-test:
	$(PYTHON) core/checker.py --self-test

test:
	$(PYTHON) -m unittest discover -s tests -v

ollama:
	$(OLLAMA) serve
