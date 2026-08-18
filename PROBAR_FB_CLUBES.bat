@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === FACEBOOK V5 - CLUBES ===
py -u facebook_worker.py --group clubes
py merge_partials.py
echo.
echo Resultado: partials\facebook_clubes.json y facebook_latest.json
pause
