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

`WORKFLOW_PARA_GITHUB.yml` está listo para usar después como GitHub Action; GitHub obliga a que los workflows estén dentro de `.github/workflows/`, así que ese paso se hace una sola vez desde la pestaña Actions.
