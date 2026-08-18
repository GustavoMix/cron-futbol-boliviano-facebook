@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo ============================================================
echo PREPARAR REPO V5.1 - SIN DESCARGAR NAVEGADOR EN GITHUB
echo ============================================================
echo.
if exist ".github\workflows\actualizar-futbol.yml" (
  del /q ".github\workflows\actualizar-futbol.yml"
  echo [OK] Eliminado workflow viejo: actualizar-futbol.yml
) else (
  echo [OK] El workflow viejo actualizar-futbol.yml no existe.
)
if exist ".github\workflows\actualizar-json-futbol.yml" (
  del /q ".github\workflows\actualizar-json-futbol.yml"
  echo [OK] Eliminado workflow viejo: actualizar-json-futbol.yml
)
echo.
echo Workflows que deben quedar:
dir /b ".github\workflows\*.yml"
echo.
echo IMPORTANTE: ahora haz git add -A, commit y push.
echo En GitHub Actions NO debe aparecer:
echo   Instalar navegador para Facebook (Playwright)
echo.
pause
