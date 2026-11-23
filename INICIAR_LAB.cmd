@echo off
setlocal
pushd "%~dp0backend"
if errorlevel 1 goto error
set "LAB_VENV_PYTHON=.venv\Scripts\python.exe"
if exist "%LAB_VENV_PYTHON%" goto dependencies

echo Preparando el entorno de Python...
where py.exe >nul 2>&1
if not errorlevel 1 (
    py -3.13 -m venv .venv
    if not errorlevel 1 goto dependencies
    py -3 -m venv .venv
    if not errorlevel 1 goto dependencies
)
python -m venv .venv
if errorlevel 1 goto error

:dependencies
"%LAB_VENV_PYTHON%" -c "import fastapi, uvicorn, dotenv, MetaTrader5, tzdata" >nul 2>&1
if errorlevel 1 (
    echo Instalando dependencias de Python...
    "%LAB_VENV_PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto error
)

"%LAB_VENV_PYTHON%" iniciar_laboratorio.py %*
if errorlevel 1 goto error
popd
exit /b 0

:error
echo El arranque se detuvo. Revisa el mensaje de arriba.
pause
exit /b 1
