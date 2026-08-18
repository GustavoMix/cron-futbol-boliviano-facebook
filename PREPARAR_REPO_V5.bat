@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo PREPARAR REPO PARA V5
echo ============================================================
echo.
if exist ".github\workflows\actualizar-futbol.yml" (
  echo Eliminando workflow V4 antiguo: actualizar-futbol.yml
  del /q ".github\workflows\actualizar-futbol.yml"
) else (
  echo Workflow V4 antiguo no esta en esta carpeta. OK.
)
if exist ".github\workflows\actualizar-futbol.yaml" (
  echo Eliminando workflow V4 antiguo: actualizar-futbol.yaml
  del /q ".github\workflows\actualizar-futbol.yaml"
)
echo.
echo Workflows V5 disponibles:
dir /b ".github\workflows\*.yml"
echo.
echo LISTO. Ahora sube estos cambios a GitHub.
pause
