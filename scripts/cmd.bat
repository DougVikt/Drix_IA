@echo off
set ROOT=%~dp0..
set PATH=%ROOT%\ia_system\python;%ROOT%\ia_system\engine;%ROOT%\ia_system\bin;%PATH%
set OLLAMA_MODELS=%ROOT%\ia_system\models
cd /d "%ROOT%"
cmd /k
