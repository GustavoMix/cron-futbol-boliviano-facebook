@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo V5 COMPLETO LOCAL - NO INSTALA DEPENDENCIAS
 echo ============================================================
py -u facebook_worker.py --group oficiales
py -u facebook_worker.py --group clubes
py -u facebook_worker.py --group medios
py -u web_worker.py
py merge_partials.py
echo.
echo LISTO: app_feed.json / facebook_latest.json / current_tables.json
pause
