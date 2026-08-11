# Fútbol Bolivia — SUPER FÁCIL

Esta versión **no tiene carpetas** y la configuración de fuentes ya está dentro de `main.py`.

## Para subir a GitHub
1. Descomprime el ZIP.
2. GitHub > Add file > Upload files > Choose your files.
3. En Windows presiona Ctrl+A: ahora todos son archivos, no hay carpetas.
4. Abrir/Subir y luego Commit changes.

## Qué hace
Al ejecutar `python main.py` crea automáticamente en la raíz:
- bolivia.json
- conmebol.json
- internacional.json
- social.json
- latest.json
- manifest.json

## Redes
Sin claves funciona la parte web. Facebook, X y YouTube se activan al configurar sus claves.

## Cron automático (GitHub Actions)
El workflow `.github/workflows/actualizar-futbol.yml` ya está activo y corre solo:
- Se ejecuta cada 30 minutos (`7,37 * * * *`).
- Tiene un `concurrency.group` que evita corridas simultáneas: si una ejecución
  todavía sigue corriendo cuando toca la siguiente, la nueva queda en cola en
  vez de arrancar en paralelo, así nunca se pisan 3-4 corridas al mismo tiempo.
- Se puede disparar manualmente desde la pestaña Actions con "Run workflow".

Para que pueda hacer `git push` con los JSON actualizados no se necesita ningún
secreto extra (usa el `GITHUB_TOKEN` automático); las claves de Meta/X/YouTube
son opcionales y se configuran como Secrets del repo si se quieren activar esas
fuentes.
