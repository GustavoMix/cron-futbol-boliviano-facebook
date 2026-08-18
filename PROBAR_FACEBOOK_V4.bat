@echo off
chcp 65001 >nul
cd /d "%~dp0"
title FUTBOL BOLIVIANO - FACEBOOK V4 MEDIA
cls
echo ============================================================
echo  FACEBOOK V4 - POSTS + FECHAS + IMAGENES + VIDEO
echo ============================================================
echo.
py -u PROBAR_SOLO_FACEBOOK.py
if errorlevel 1 (
  echo.
  echo ERROR: revisa el mensaje de arriba.
)
echo.
pause
