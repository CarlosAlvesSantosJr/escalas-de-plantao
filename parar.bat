@echo off
cd /d "%~dp0"
echo Desligando a Escala de Plantao (os dados ficam salvos na pasta "dados")...
docker compose down
timeout /t 4 >nul
