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

## Facebook híbrido (actualizado)

El proyecto ahora soporta dos caminos para Facebook:

1. **Graph API oficial**: si existe `META_ACCESS_TOKEN`, usa la API de Meta.
2. **Página pública**: si no hay token, `mode: auto` intenta leer únicamente contenido que Facebook expone públicamente (Page Plugin / página pública), sin login y sin evadir controles.

Las páginas están en `sources.yaml` bajo `facebook.public_pages`. Para agregar otra, basta añadir `name`, `url`, `scope`, `competition` y `authority`.

El resultado entra en `social.json` con `source_type` igual a `facebook` o `facebook_public_web` y en `extra.collector` se indica `graph_api` o `public_web`.

> Nota: Meta puede decidir no exponer el timeline de una página a visitantes sin sesión. En ese caso esa fuente queda registrada en `manifest.json` y el cron continúa con las demás fuentes; no se intenta saltar el login ni los controles de Meta.

## Facebook sin token - V2

El recolector intenta tres caminos en orden:
1. Meta Graph API, solo si existe `META_ACCESS_TOKEN` con permisos válidos.
2. HTML público rápido.
3. Navegador real Edge/Chrome con Playwright para renderizar el JavaScript visible públicamente.

No inicia sesión, no reutiliza cookies y no intenta eludir controles de Meta. Si Meta muestra un muro de inicio de sesión para una página, esa fuente se marca como no disponible y el cron continúa.

Para probar únicamente Facebook en Windows, usa `PROBAR_SOLO_FACEBOOK.bat`.
