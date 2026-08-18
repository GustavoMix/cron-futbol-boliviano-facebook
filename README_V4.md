# Fútbol Boliviano V4 — Facebook + media + JSON para app

## Qué cambia

- Facebook va **directo por Edge/Chrome**. El HTTP antiguo queda desactivado por defecto porque la prueba devolvió HTTP 400 en todas las páginas.
- Hace scroll limitado y busca hasta **8 publicaciones actuales por página**.
- Filtra Facebook a **72 horas** cuando puede determinar la fecha.
- Descarta publicaciones antiguas como la de Futbolmanía 2023.
- Extrae URL estable del post/reel, imágenes/miniaturas visibles y, si el navegador expone una URL HTTP directa de video, la guarda.
- Una URL directa de video de CDN puede expirar; para una app se debe tratar `url` / `video_post_url` como referencia estable.
- Genera `facebook_latest.json`, `app_feed.json` y `current_tables.json`.
- `current_tables.json` elige la mejor tabla por competición/tipo, priorizando FBF/autoridad y tablas con más filas.

## Prueba rápida

1. Ejecuta `PROBAR_FACEBOOK_V4.bat`.
2. Mira `facebook_test.json`.
3. Si funciona, ejecuta `EJECUTAR_CRON_V4.bat`.

## Campos útiles para Kotlin

- `url`: URL estable del post/reel.
- `image_url`: imagen principal visible.
- `thumbnail_url`: miniatura preferida.
- `video_url`: video directo solo cuando Facebook lo expone; puede expirar.
- `media_type`: `text`, `image`, `video` o `reel`.
- `published_at`: fecha UTC ISO cuando se pudo interpretar.
- `extra.media.images`: lista de imágenes encontradas.
- `extra.media.video_post_url`: URL estable al post/reel de Facebook.
- `extra.media.direct_video_urls`: enlaces directos visibles, potencialmente temporales.
- `extra.engagement`: comentarios/compartidos cuando se pueden extraer con seguridad.

## Fuentes Facebook

La V4 conserva las 9 fuentes probadas y agrega tres páginas oficiales verificadas: Always Ready, Club Aurora y Real Tomayapo.
