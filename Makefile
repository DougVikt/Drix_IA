# Identifica o comando principal e os argumentos
COMMAND    := $(firstword $(MAKECMDGOALS))
ARG := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))

# Silencia os argumentos para o Make 3.81 não tentar executá-los
$(eval $(ARGUMENTOS):;@:)

# Variáveis
PYTHON = poetry run python
OLLAMA = ./ia_system/engine/ollama.exe
SHELL = cmd.exe   # Necessário para make.exe do GnuWin32 no Windows

.PHONY: help install run learn shell clean ui setup-media backup logs status web dump

help:
	@echo "Comandos disponíveis para IA Portátil:"
	@echo "  make install     	- Instala dependências via Poetry"
	@echo "  make add ARG   	- Adiciona dependências via Poetry"
	@echo "  make remove ARG	- Remove dependências via Poetry"
	@echo "  make info ARG		- Lista versões das dependências(ARG para especifico)"
	@echo "  make up			- Atualiza dependências contidas no Poetry"
	@echo "  make run         	- Inicia a IA em modo chat (terminal)"
	@echo "  make web         	- Inicia interface web (FastAPI)"
	@echo "  make ui          	- Inicia a interface gráfica (CustomTkinter)"
	@echo "  make learn       	- Força atualização do aprendizado (RAG)"
	@echo "  make backup      	- Faz backup do banco vetorial"
	@echo "  make logs        	- Mostra os logs da sessão atual"
	@echo "  make sync       	- Sincroniza config, modelos, skills e dump"
	@echo "  make status      	- Mostra status do sistema"
	@echo "  make shell       	- Abre terminal do Poetry no HD"
	@echo "  make clean       	- Limpa caches e .venv"
	@echo "  make dump        	- Atualiza o dump cumulativo da Drix"
	@echo "  make setup-media 	- Baixa modelos de imagem/áudio"

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

run:
	$(PYTHON) core/main.py --interface

web:
	$(PYTHON) -m ui.web_app

ui:
	poetry run python -m ui.app

learn:
	$(PYTHON) core/main.py --update-db

dump:
	$(PYTHON) scripts/update_dump.py "Manual dump update"

backup:
	$(PYTHON) scripts/backup.py

logs:
	@if exist logs\drix.log type logs\drix.log

sync:
	$(PYTHON) -m core.config_auto

status:
	$(PYTHON) scripts/status.py

shell:
	poetry shell $(ARG)

up: 
	poetry update $(ARG)

clean:
	@if exist .venv rmdir /s /q .venv
	@if exist ia_system\poetry_cache rmdir /s /q ia_system\poetry_cache
	@if exist __pycache__ rmdir /s /q __pycache__
	@echo "Caches limpos."

setup-media:
	$(PYTHON) scripts/download_media_models.py

ollama:
	cd $(OLLAMA)

