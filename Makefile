# Identifica o comando principal e os argumentos
COMMAND    := $(firstword $(MAKECMDGOALS))
ARG := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))

# Silencia os argumentos para o Make 3.81 não tentar executá-los
$(eval $(ARGUMENTOS):;@:)

# Variáveis
PYTHON = poetry run python
OLLAMA = ./ia_system/engine/ollama.exe
SHELL = cmd.exe   # Necessário para make.exe do GnuWin32 no Windows

.PHONY: help install run learn shell clean ui setup-media

help:
	@echo "Comandos disponíveis para IA Portátil:"
	@echo "  make install     	- Instala dependências via Poetry"
	@echo "  make add ARG   	- Adiciona dependências via Poetry"
	@echo "  make remove ARG	- Remove dependências via Poetry"
	@echo "  make info ARG		- Lista versões das dependências(ARG para especifico)"
	@echo "  make up			- Atualiza dependências contidas no Poetry"
	@echo "  make run         	- Inicia a IA em modo chat"
	@echo "  make ui          	- Inicia a interface gráfica (Streamlit)"
	@echo "  make learn       	- Força atualização do aprendizado (RAG)"
	@echo "  make shell       	- Abre terminal do Poetry no HD"
	@echo "  make clean       	- Limpa caches e .venv"
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
	$(PYTHON) app.py

ui:
	poetry run streamlit run ui/app.py

learn:
	$(PYTHON) main.py --update-db

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

