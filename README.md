# Fútbol Bolivia Aggregator

Scraper/agregador en Python pensado para una futura app Android/Kotlin. Reúne información de fútbol boliviano, torneos CONMEBOL y redes sociales, y genera JSON pequeños y separados.

## Qué cubre

- FBF: noticias, División Profesional, Copa de la División Profesional/Copa Paceña, Copa Simón Bolívar, Sub-19 y Sub-16.
- Selección boliviana y contenido FIFA configurable.
- CONMEBOL Libertadores y Sudamericana, FIFA y fuentes internacionales configurables, incluyendo Concacaf Champions Cup y Nations League.
- Facebook mediante Meta Graph API (no hace scraping del HTML de Facebook).
- X mediante X API v2 Recent Search.
- YouTube mediante YouTube Data API v3.
- Deduplicación de noticias repetidas.
- Ranking por fecha real de publicación + autoridad de la fuente.

## La regla importante de frescura

Se guardan dos campos distintos:

- `published_at`: fecha/hora original publicada por la fuente.
- `scraped_at`: fecha/hora en que este proceso encontró el contenido.

Para `news`, `social` y `video`, el ranking usa aproximadamente **72% frescura + 28% autoridad**. Así una publicación oficial de Facebook hecha hace minutos puede quedar por encima de una página FBF que se actualizó hace semanas.

Para tablas/resultados/datos estructurados usa **75% autoridad + 25% frescura**, porque allí la fuente oficial debe mandar incluso si se actualiza con menos frecuencia.

## Instalación Windows

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
py main.py
```

Sin tokens de redes sociales el programa **igual ejecuta las páginas web** y deja avisos en `output/manifest.json`.

## Tokens opcionales

Edita `.env`:

```env
META_ACCESS_TOKEN=...
META_GRAPH_VERSION=v26.0
X_BEARER_TOKEN=...
YOUTUBE_API_KEY=...
```

### Facebook

Para leer páginas públicas de terceros de forma estable se usa Meta Graph API y la función/permiso correspondiente a Page Public Content Access. El módulo busca la página por nombre y luego consulta sus posts. Si Meta no autoriza ese acceso para tu app, el módulo se omite y el resto continúa.

### X

Usa `/2/tweets/search/recent`. Las búsquedas están en `config/sources.yaml`.

### YouTube

Busca videos recientes por palabras clave, ordenados por fecha y con `regionCode=BO`.

## JSON generados

- `output/bolivia.json`
- `output/conmebol.json`
- `output/internacional.json`
- `output/social.json`
- `output/latest.json` ← feed general ordenado por frescura
- `output/manifest.json`

Ejemplo simplificado de un item:

```json
{
  "id": "...",
  "kind": "news",
  "title": "...",
  "text": "...",
  "url": "...",
  "image_url": "...",
  "published_at": "2026-08-11T15:10:00Z",
  "scraped_at": "2026-08-11T15:18:03Z",
  "source_name": "...",
  "source_type": "facebook",
  "source_authority": 0.98,
  "scope": "bolivia",
  "competition": "seleccion_bolivia",
  "rank_score": 0.94
}
```

## Cómo lo consumiría Kotlin

Tu app puede empezar descargando solo `manifest.json`. Según el menú descarga el archivo necesario:

- Fútbol Boliviano → `bolivia.json`
- Libertadores / Sudamericana → `conmebol.json`
- Mundo / Selección / FIFA → `internacional.json`
- Últimas noticias → `latest.json`
- Solo redes → `social.json`

Esto evita bajar un JSON enorme cada vez.

## Agregar más fuentes

No toques Python para cada fuente. Agrega una entrada a `config/sources.yaml` con:

```yaml
- id: mi_fuente
  enabled: true
  name: Nombre visible
  url: https://ejemplo.com/futbol
  scope: bolivia
  competition: general
  source_type: media
  authority: 0.75
```

El parser genérico intenta encontrar artículos, JSON-LD y tablas HTML. Si una página usa JavaScript privado o una estructura especial, conviene crear un provider específico para esa fuente.

## GitHub Actions

Incluye `.github/workflows/update-football.yml`. Corre dos veces por hora y commitea los JSON si hubo cambios. Para redes, crea estos Repository Secrets:

- `META_ACCESS_TOKEN`
- `X_BEARER_TOKEN`
- `YOUTUBE_API_KEY`

## Importante

Este proyecto no intenta evadir bloqueos, CAPTCHAs ni sistemas anti-bot. Para plataformas como Facebook/X/YouTube usa sus APIs. Para sitios web normales respeta sus condiciones de uso y robots/ritmo de solicitudes.
