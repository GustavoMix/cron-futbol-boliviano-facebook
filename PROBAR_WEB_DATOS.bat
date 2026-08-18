@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === WEB V5 - NOTICIAS Y TABLAS ===
py -u web_worker.py
py merge_partials.py
echo.
echo Resultado: partials\web + app_feed.json + current_tables.json
pause
