@echo off
rem Enciende la demo completa (servidor + pantallas) y abre el navegador. Para apagar: cerrar las dos ventanas negras.
title Protocolos de Calidad - demo
start "1 servidor (Python) - no cerrar" /d "C:\Users\maryc\protocolos-calidad" cmd /k ".venv\Scripts\python herramientas\demo_local.py"
start "2 pantallas (Lovable) - no cerrar" /d "C:\Users\maryc\quality-standards-hub" cmd /k "set VITE_API_URL=http://localhost:8001&& npx.cmd vite --port 5182"
echo Encendiendo la demo... se abrira el navegador en unos segundos.
timeout /t 15 /nobreak >nul
start "" http://localhost:5182
