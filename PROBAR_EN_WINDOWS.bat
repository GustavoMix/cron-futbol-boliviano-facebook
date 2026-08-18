@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -m pip install -r requirements.txt
if errorlevel 1 goto :error
py main.py --config sources.yaml --output .
if errorlevel 1 goto :error
echo.
echo Terminado. Revisa social.json y manifest.json
pause
exit /b 0
:error
echo.
echo Ocurrio un error.
pause
exit /b 1
