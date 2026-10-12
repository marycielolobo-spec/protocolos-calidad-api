@echo off
rem Inicia Protocolos de Calidad. Doble clic para abrir; cerrar esta ventana para apagar.
rem La primera vez instala lo necesario (tarda unos minutos).
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Preparando Python por primera vez...
  py -m venv .venv || goto :error
)
".venv\Scripts\python.exe" -m pip install -q -r requirements.txt || goto :error

echo.
echo  Protocolos de Calidad: http://localhost:8000
echo  Para apagar el sistema, cierre esta ventana.
echo.
start "" http://localhost:8000
".venv\Scripts\python.exe" -m uvicorn servidor.main:app --host 127.0.0.1 --port 8000
goto :eof

:error
echo.
echo  No se pudo iniciar. Verifique que Python este instalado (https://www.python.org/downloads/).
pause
