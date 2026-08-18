@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === FACEBOOK V5 - MEDIOS ===
py -u facebook_worker.py --group medios
py merge_partials.py
echo.
echo Resultado: partials\facebook_medios.json y facebook_latest.json
pause
