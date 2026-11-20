@echo off
set ROOT=%~dp0..
set PATH=%ROOT%\ia_system\python\python-3.10.11.amd64;%ROOT%\ia_system\engine;%ROOT%\ia_system\bin;%PATH%
set OLLAMA_MODELS=%ROOT%\ia_system\models
set PYTHONPATH=%ROOT%\.venv\Lib\site-packages
cd /d "%ROOT%"
cmd /k