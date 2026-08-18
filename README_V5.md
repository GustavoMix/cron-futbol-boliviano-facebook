# V5.1 RAPIDA — SIN INSTALAR CHROME EN GITHUB

Esta variante elimina `python -m playwright install chromium` de GitHub Actions y usa directamente el Chrome del runner. Si todavía ves `Actualizar JSON fútbol`, estás ejecutando el workflow viejo.

# Fútbol Boliviano V5 — rápido, por grupos y listo para app

Esta versión reemplaza el cron único pesado por **4 trabajos separados**.

## Qué cambia

1. **Facebook HTTP directo queda desactivado.** En las pruebas reales devolvía HTTP 400 y solo hacía perder tiempo.
2. Facebook se divide en 3 grupos:
   - `oficiales`: FBF, Bolívar, The Strongest, Always Ready.
   - `clubes`: Oriente, Blooming, Aurora, Real Tomayapo.
   - `medios`: Tigo Sports, Futbolmanía, FutbolCanal, Red Uno.
3. El cuarto trabajo recoge **webs, noticias y tablas**.
4. Cada grupo guarda su propio JSON en `partials/`.
5. `merge_partials.py` une lo último disponible y genera los JSON de la app.
6. Si Facebook falla temporalmente, **no borra el último resultado bueno**. Mantiene caché de hasta 7 días.

## Velocidad en GitHub Actions

La V4 instalaba Playwright y luego descargaba Chromium en cada runner. Esa descarga podía tardar 30–40 segundos.

La V5 hace esto:

- Facebook instala solo `playwright + PyYAML`.
- Usa el **Google Chrome que ya trae el runner `ubuntu-latest`** cuando está disponible.
- Solo si Chrome no existe, instala Chromium como fallback.
- El fallback queda cacheado con `actions/cache`.
- `setup-python` usa caché de pip.
- El job web **no instala Playwright**.

Por eso normalmente desaparece el paso pesado `Install Playwright Chromium`.

## Horarios incluidos

Para reducir carga y minutos de GitHub:

- Oficiales: minuto 07 cada 2 horas.
- Clubes: minuto 27 cada 2 horas.
- Medios: minuto 47 cada 2 horas.
- Web/datos: minuto 57 cada hora.

Están separados para que no golpeen todas las fuentes a la vez y para reducir conflictos al hacer push.

## JSON para Kotlin

### `facebook_latest.json`
Publicaciones Facebook de los 3 grupos, deduplicadas.

Campos de media importantes:

- `image_url`: imagen principal.
- `thumbnail_url`: miniatura principal.
- `video_url`: URL directa si el navegador la expone. **Puede caducar**.
- `video_post_url`: URL estable del post/reel.
- `media_type`: `text`, `image`, `video` o `reel`.
- `extra.media.images`: lista de imágenes encontradas con tamaño.
- `extra.media.videos`: URLs directas visibles en ese momento.
- `post_id`: ID útil para deduplicar en Kotlin/Supabase.
- `published_at`: fecha normalizada cuando Facebook la expone.

Para video en la app, conserva siempre `video_post_url/post_url`. No dependas únicamente de `video_url` porque las URLs CDN de Facebook pueden caducar.

### `app_feed.json`
Feed final para la app: mezcla web + Facebook y elimina duplicados.

### `current_tables.json`
Selección automática de la tabla estructurada más adecuada por competición. Se priorizan las fuentes con mayor autoridad/oficiales.

### `latest.json`
Noticias y contenido social reciente.

## Fuentes web agregadas en V5

Además de FBF/CONMEBOL/FIFA, `sources.yaml` incluye:

- Red Uno — Super Deportivo.
- Red Uno — Fútbol Boliviano.
- Unitel — A Todo Deporte.
- Unitel — División Profesional.
- DIEZ — Fútbol.
- DIEZ — Fútbol Boliviano.
- Red Uno — Stats Center Bolivia.

## Windows

Primera vez solamente:

`INSTALAR_UNA_SOLA_VEZ.bat`

Después NO vuelvas a instalar nada. Para probar:

- `PROBAR_FB_OFICIALES.bat`
- `PROBAR_FB_CLUBES.bat`
- `PROBAR_FB_MEDIOS.bat`
- `PROBAR_WEB_DATOS.bat`

O todo junto:

`EJECUTAR_TODO_LOCAL.bat`

En Windows usa Microsoft Edge instalado en el sistema; no necesita descargar Chromium de Playwright.

## GitHub

Copia el contenido de esta carpeta a la raíz del repositorio. La carpeta `.github/workflows/` ya contiene los 4 workflows nuevos.

**Importante:** elimina/desactiva el workflow V4 anterior que ejecutaba todo junto. En este paquete ya no está incluido.
