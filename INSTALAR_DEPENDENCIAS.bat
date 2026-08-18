@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalar dependencias - Futbol Bolivia
py -m pip install -r requirements.txt
pause
