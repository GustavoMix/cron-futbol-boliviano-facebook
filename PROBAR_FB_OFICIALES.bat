@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === FACEBOOK V5 - OFICIALES ===
py -u facebook_worker.py --group oficiales
py merge_partials.py
echo.
echo Resultado: partials\facebook_oficiales.json y facebook_latest.json
pause
