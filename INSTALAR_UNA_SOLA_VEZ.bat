@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo INSTALACION V5 - SOLO UNA VEZ EN ESTA PC
echo ============================================================
echo.
py -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto error
echo.
echo LISTO. NO se instala Chromium porque Windows ya usa Edge.
echo Las proximas pruebas NO vuelven a instalar dependencias.
pause
exit /b 0
:error
echo.
echo ERROR instalando dependencias.
pause
exit /b 1
