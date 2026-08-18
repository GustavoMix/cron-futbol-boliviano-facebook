@echo off
chcp 65001 >nul
cd /d "%~dp0"
title FUTBOL BOLIVIANO - PRUEBA FACEBOOK EN VIVO
cls
echo ============================================================
echo  FACEBOOK FUTBOL BOLIVIANO - PRUEBA EN VIVO
echo ============================================================
echo.
echo Se mostrara CADA pagina mientras se prueba.
echo No se instalaran paquetes en esta prueba.
echo.
py -u PROBAR_SOLO_FACEBOOK.py
if errorlevel 1 goto :error
echo.
echo ============================================================
echo PRUEBA TERMINADA
echo ============================================================
pause
exit /b 0
:error
echo.
echo ERROR AL EJECUTAR.
echo Si dice que falta un modulo, ejecuta INSTALAR_DEPENDENCIAS.bat.
pause
exit /b 1
