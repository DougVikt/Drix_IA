@echo off
set ROOT=%~dp0
set PATH=%ROOT%ia_system\python;%ROOT%ia_system\bin;%ROOT%ia_system\engine;%PATH%
set OLLAMA_MODELS=%ROOT%ia_system\models
cd /d "%ROOT%"
.venv\Scripts\python.exe core\checker.py
