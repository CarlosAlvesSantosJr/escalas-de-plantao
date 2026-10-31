@echo off
chcp 65001 >nul
title Escala de Plantao - SAMU 192
cd /d "%~dp0"

echo.
echo  ==============================================
echo    Escala de Plantao - SAMU 192
echo  ==============================================
echo.

docker info >nul 2>&1
if errorlevel 1 (
    echo  O Docker Desktop nao esta aberto. Abrindo...
    start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"
    echo  Aguardando o Docker iniciar (pode levar 1 minuto^)...
    :espera_docker
    timeout /t 3 /nobreak >nul
    docker info >nul 2>&1
    if errorlevel 1 goto espera_docker
)

if not exist dados mkdir dados

echo  Iniciando a aplicacao...
docker compose up -d --build
if errorlevel 1 (
    echo.
    echo  Algo deu errado. Tire um print desta tela e envie ao suporte.
    pause
    exit /b 1
)

echo  Aguardando a aplicacao responder...
:espera_app
timeout /t 2 /nobreak >nul
curl -s -o nul http://localhost:8080/saude
if errorlevel 1 goto espera_app

start "" http://localhost:8080
echo.
echo  Pronto! A escala abriu no navegador: http://localhost:8080
echo  Pode fechar esta janela. Para desligar, use "parar.bat".
echo.
timeout /t 8 >nul
