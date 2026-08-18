@echo off
chcp 65001 >nul
cd /d "%~dp0"
title FUTBOL BOLIVIANO - CRON V4
cls
echo ============================================================
echo  FUTBOL BOLIVIANO - CRON V4 PARA APP
 echo ============================================================
echo Genera: app_feed.json, facebook_latest.json, current_tables.json
echo.
py -u main.py --config sources.yaml --output .
echo.
echo FINALIZADO. Revisa manifest.json y los JSON generados.
pause
