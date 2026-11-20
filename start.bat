@echo off
setlocal EnableExtensions
set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PY=%ROOT%ia_system\python\python-3.10.11.amd64\python.exe"
set "PYW=%ROOT%ia_system\python\python-3.10.11.amd64\pythonw.exe"
set "ENGINE=%ROOT%ia_system\engine\ollama.exe"
set "LOG=%ROOT%logs\startup.log"

if not exist "%ROOT%logs" mkdir "%ROOT%logs" >nul 2>&1

set "PATH=%ROOT%ia_system\python\python-3.10.11.amd64;%ROOT%ia_system\engine;%ROOT%ia_system\bin;%PATH%"
set "OLLAMA_MODELS=%ROOT%ia_system\models"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if exist "%ROOT%.venv\Lib\site-packages" set "PYTHONPATH=%ROOT%.venv\Lib\site-packages"

echo.>>"%LOG%"
echo [%date% %time%] start.bat: iniciando Drix>>"%LOG%"

if not exist "%PY%" goto :no_python
if not exist "%ROOT%core\checker.py" goto :no_checker
if not exist "%ROOT%.venv\Lib\site-packages\fastapi" goto :no_libs
if not exist "%ENGINE%" echo [%date% %time%] AVISO: ollama.exe nao encontrado em "%ENGINE%">>"%LOG%"

rem Teste rapido do interpretador antes de carregar o restante.
"%PY%" -c "import sys" >>"%LOG%" 2>&1
if errorlevel 1 goto :bad_python

"%PY%" -u "%ROOT%core\checker.py" %* 2>>"%LOG%"
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" goto :failed
exit /b 0

:no_python
echo.
echo  ERRO: o Python portatil da Drix nao foi encontrado.
echo  Esperado em: "%PY%"
echo.
echo  Copie a pasta "ia_system" inteira para o mesmo local da Drix.
echo  Se voce baixou apenas o codigo, restaure o pacote completo.
echo [%date% %time%] ERRO: Python portatil ausente: %PY%>>"%LOG%"
goto :hold

:no_checker
echo.
echo  ERRO: arquivo core\checker.py nao encontrado.
echo  O pacote da Drix esta incompleto ou foi movido sem a pasta core.
echo [%date% %time%] ERRO: core\checker.py ausente>>"%LOG%"
goto :hold

:no_libs
echo.
echo  ERRO: as bibliotecas da Drix nao foram encontradas.
echo  Esperado em: "%ROOT%.venv\Lib\site-packages"
echo.
echo  Copie a pasta ".venv" junto com a Drix. Ela contem FastAPI, Ollama,
echo  PyTorch e as demais dependencias testadas.
echo [%date% %time%] ERRO: .venv\Lib\site-packages ausente>>"%LOG%"
goto :hold

:bad_python
echo.
echo  ERRO: o Python portatil nao conseguiu iniciar.
echo  Isso normalmente indica arquivos faltando ou bloqueados pelo antivirus.
echo.
echo  Teste manual:
echo    "%PY%" -c "import sys; print(sys.version)"
echo.
echo  Saida do teste:
"%PY%" -c "import sys; print(sys.version)" 2>&1
echo [%date% %time%] ERRO: falha ao iniciar o Python portatil>>"%LOG%"
goto :hold

:failed
echo.
echo  A Drix nao conseguiu iniciar (codigo %CODE%).
echo  Log de inicializacao: "%LOG%"
echo  Log da aplicacao:    "%ROOT%logs\drix.log"
echo.
echo  Ultimas linhas da inicializacao:
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Test-Path -LiteralPath '%LOG%') { Get-Content -LiteralPath '%LOG%' -Encoding UTF8 -Tail 25 }" 2>nul
if errorlevel 1 type "%LOG%"
if exist "%ROOT%logs\drix.log" (
  echo.
  echo  Ultimas linhas da aplicacao:
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -LiteralPath '%ROOT%logs\drix.log' -Encoding UTF8 -Tail 15" 2>nul
)
goto :hold

:hold
echo.
echo  Pressione qualquer tecla para fechar...
pause >nul
exit /b 1