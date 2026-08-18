@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ==============================================
echo FUTBOL BOLIVIANO - CRON HIBRIDO FACEBOOK
echo ==============================================
echo.
py -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Ejecutando recolector...
py main.py --config sources.yaml --output .
if errorlevel 1 goto :error

echo.
echo ===== RESULTADO FACEBOOK =====
powershell -NoProfile -Command "$j=Get-Content -Raw -Encoding UTF8 'social.json' | ConvertFrom-Json; $fb=@($j.items | Where-Object { ($_.source_type -like 'facebook*') }); Write-Host ('Posts Facebook encontrados: ' + $fb.Count); $fb | Select-Object -First 10 source_name,title,url | Format-Table -Wrap"
echo.
echo Revisa tambien manifest.json y social.json
pause
exit /b 0

:error
echo.
echo ERROR al ejecutar. Revisa el mensaje de arriba.
pause
exit /b 1
