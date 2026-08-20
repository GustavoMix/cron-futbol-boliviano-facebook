from __future__ import annotations

import mimetypes
import os
import re
import time
import traceback
import unicodedata
from pathlib import Path
from typing import Any

import requests

LOGO_BUCKET = "team-logos"
# Escudos que ningún buscador automático encuentra (clubes chicos/regionales
# sin Wikipedia): se ponen los archivos de imagen acá, con el nombre del
# equipo como nombre de archivo (ej. "real_potosi.png", espacios con guion
# bajo, sin tildes), y el cron los sube solo en cada corrida.
MANUAL_LOGOS_DIR = Path(__file__).resolve().parent / "manual_logos"
# Wikimedia exige un User-Agent descriptivo (con contacto) y bloquea con 429
# a quien no lo manda o pide muy seguido. Con ~150 escudos en la primera
# corrida, bajarlos todos sin pausa dispara ese límite casi de inmediato.
LOGO_USER_AGENT = (
    "FutbolBolivianoAggregator/1.0 "
    "(+https://github.com/GustavoMix/cron-futbol-boliviano-facebook; contacto: gustavotna4@gmail.com)"
)
LOGO_DOWNLOAD_MIN_INTERVAL = 1.5
_logo_download_last_call = [0.0]


def _remove_solid_background(image_bytes: bytes, original_content_type: str) -> tuple[bytes, str]:
    """Convierte a transparente el fondo de un escudo, si tiene uno sólido y
    claro (blanco, gris claro, etc.) — típico de fotos JPG, que no soportan
    transparencia y se ven como un cuadro feo sobre el fondo oscuro de la
    app. Se fija en las 4 esquinas: si son parecidas entre sí y claras, se
    asume que ESE es el fondo y se hace transparente todo lo que se le
    parezca (con un borde suavizado para que no quede dentado). Si las
    esquinas no son consistentes (ej. el escudo ya llega hasta el borde),
    no se toca nada — mejor dejar la imagen tal cual que arruinarla.
    Devuelve (bytes_png, content_type); si no se pudo procesar (falta
    Pillow, imagen corrupta, etc.) devuelve la imagen original sin tocar.
    """
    try:
        from PIL import Image
        import io
    except ImportError:
        return image_bytes, original_content_type

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        w, h = img.size
        corners = [img.getpixel((0, 0)), img.getpixel((w - 1, 0)), img.getpixel((0, h - 1)), img.getpixel((w - 1, h - 1))]
        r0, g0, b0 = corners[0][:3]
        is_light = r0 > 225 and g0 > 225 and b0 > 225
        consistent = all(abs(c[0] - r0) < 18 and abs(c[1] - g0) < 18 and abs(c[2] - b0) < 18 for c in corners)
        if not (is_light and consistent):
            return image_bytes, original_content_type

        pixels = img.load()
        soft_start, hard_cut = 20, 55  # distancia de color: <soft_start = totalmente transparente, >hard_cut = opaco
        for y in range(h):
            for x in range(w):
                r, g, b, a = pixels[x, y]
                dist = max(abs(r - r0), abs(g - g0), abs(b - b0))
                if dist <= soft_start:
                    pixels[x, y] = (r, g, b, 0)
                elif dist < hard_cut:
                    factor = (dist - soft_start) / (hard_cut - soft_start)
                    pixels[x, y] = (r, g, b, int(a * factor))

        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue(), "image/png"
    except Exception:
        return image_bytes, original_content_type


def _logo_download_throttle() -> None:
    wait = LOGO_DOWNLOAD_MIN_INTERVAL - (time.monotonic() - _logo_download_last_call[0])
    if wait > 0:
        time.sleep(wait)
    _logo_download_last_call[0] = time.monotonic()


def _with_retries(fn, attempts: int = 3, base_delay: float = 2.0):
    """PGRST002 ('Could not query the database for the schema cache. Retrying.')
    es transitorio: el proyecto es plan Free, con recursos chicos, y un ratito
    de carga (ej. justo despues de exponer tablas nuevas, o muchos pedidos
    seguidos) hace que PostgREST tarde en refrescar su cache interno. Sin
    reintentos, la PRIMERA falla (la lectura de team_logos ya subidos) hacia
    que TODOS los equipos se traten como "nunca subidos" y se volviera a
    intentar subir los ~150, lo que a su vez generaba mas carga todavia."""
    last_exc = None
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if "PGRST002" not in str(exc) and "503" not in str(exc):
                raise
            if attempt < attempts - 1:
                time.sleep(base_delay * (attempt + 1))
    raise last_exc

# Envío de datos ya calculados por main.py (Item[] + build_current_tables) hacia Supabase.
# No repite el scraping/parsing: reutiliza exactamente lo que ya produce current_tables.json,
# que es lo mismo que hoy consume la app vía GitHub. Si faltan las credenciales, no hace nada
# (permite seguir corriendo el cron localmente sin Supabase configurado).


def _norm_header(value: str) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _normalize_team_key(value: str) -> str:
    # Debe coincidir con normalize_title() de main.py para calzar con las
    # claves de team_assets (que ya vienen normalizadas de la misma forma).
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c)).lower()
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


STANDINGS_MAP = {
    "pos": "posicion", "equipo": "equipo", "club": "equipo", "pts": "pts", "puntos": "pts",
    "pj": "pj", "g": "g", "e": "e", "p": "p", "gf": "gf", "gc": "gc",
    "dif": "dif", "dg": "dif", "clasificacion": "clasificacion",
}
TOP_SCORERS_MAP = {"pos": "posicion", "jugador": "jugador", "goles": "goles", "penales": "penales"}
ASSISTS_MAP = {"pos": "posicion", "jugador": "jugador", "asistencias": "asistencias"}
MATCHES_MAP = {
    "fecha": "fecha", "local": "local", "resultado": "resultado", "visitante": "visitante",
    "estadio": "estadio", "fechapartido": "fecha_partido", "hora": "hora",
    "locallogo": "local_logo", "visitantelogo": "visitante_logo",
}

INT_COLUMNS = {"posicion", "pts", "pj", "g", "e", "p", "gf", "gc", "dif", "goles", "penales", "asistencias"}


def _row_to_record(header: list[str], row: list[str], column_map: dict[str, str]) -> dict[str, Any]:
    record: dict[str, Any] = {}
    for idx, raw_h in enumerate(header):
        col = column_map.get(_norm_header(raw_h))
        if not col or idx >= len(row):
            continue
        value = str(row[idx]).strip()
        if col in INT_COLUMNS:
            m = re.search(r"-?\d+", value.replace(",", ""))
            if m:
                record[col] = int(m.group(0))
            # Si no hay número (celda vacía, fusionada por rowspan, etc.):
            # NO se manda la clave. Un upsert solo actualiza las columnas
            # presentes en el payload, así que omitirla deja el valor
            # anterior intacto en vez de pisarlo con 0 por una corrida que
            # no trajo dato nuevo para ese campo puntual.
        else:
            record[col] = value
    return record


def _get_client():
    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not url or not key:
        return None
    try:
        from supabase import create_client
    except ImportError:
        print("supabase_sync: paquete 'supabase' no instalado, se omite el guardado en Supabase.", flush=True)
        return None
    return create_client(url, key)


def _upsert(client, table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
    if not rows:
        return
    try:
        _with_retries(lambda: client.schema("futbol_boliviano").table(table).upsert(rows, on_conflict=on_conflict).execute())
        print(f"supabase_sync: {table} <- {len(rows)} filas", flush=True)
    except Exception as exc:
        print(f"supabase_sync: ERROR en {table}: {type(exc).__name__}: {exc}", flush=True)


def _dedupe_rows(rows: list[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    # Postgres rechaza un upsert que "toca" la misma fila dos veces en el
    # mismo comando (ON CONFLICT DO UPDATE ... "cannot affect row a second
    # time"). Cuando una competición junta varias tablas parciales (grupos,
    # fases), el mismo equipo puede aparecer más de una vez con la misma
    # clave de conflicto; se conserva la última aparición.
    deduped: dict[tuple, dict[str, Any]] = {}
    for row in rows:
        key = tuple(row.get(f, "") for f in key_fields)
        deduped[key] = row
    return list(deduped.values())


def push_items(client, items: list[dict[str, Any]]) -> None:
    rows = []
    for it in items:
        if it.get("kind") not in {"news", "social", "video"}:
            continue
        rows.append({
            "id": it.get("id"),
            "kind": it.get("kind"),
            "title": (it.get("title") or "")[:500],
            "text": it.get("text") or "",
            "url": it.get("url") or "",
            "image_url": it.get("image_url") or "",
            "video_url": it.get("video_url") or "",
            "thumbnail_url": it.get("thumbnail_url") or "",
            "media_type": it.get("media_type") or "none",
            "published_at": it.get("published_at"),
            "scraped_at": it.get("scraped_at"),
            "source_id": it.get("source_id") or "",
            "source_name": it.get("source_name") or "",
            "source_type": it.get("source_type") or "",
            "source_authority": it.get("source_authority") or 0.5,
            "scope": it.get("scope") or "general",
            "competition": it.get("competition") or "general",
            "rank_score": it.get("rank_score") or 0,
            "stale": bool(it.get("stale", False)),
        })
    _upsert(client, "items", rows, on_conflict="id")


def push_current_tables(client, current_tables: dict[str, Any], logo_map: dict[str, str] | None = None) -> None:
    logo_map = logo_map or {}
    standings_rows: list[dict[str, Any]] = []
    top_scorers_rows: list[dict[str, Any]] = []
    assists_rows: list[dict[str, Any]] = []
    matches_rows: list[dict[str, Any]] = []

    for competition, blocks in (current_tables.get("competitions") or {}).items():
        standings = blocks.get("standings")
        if standings and isinstance(standings.get("extra"), dict):
            rows = standings["extra"].get("rows") or []
            if len(rows) >= 2:
                scope = standings.get("scope") or "bolivia"
                source_id = standings.get("source_id", "")
                for row in rows[1:]:
                    rec = _row_to_record(rows[0], row, STANDINGS_MAP)
                    if not rec.get("equipo"):
                        continue
                    rec.update({
                        "competition": competition, "scope": scope, "source_id": source_id,
                        "logo_url": logo_map.get(_normalize_team_key(rec["equipo"]), ""),
                    })
                    standings_rows.append(rec)

        top_scorers = blocks.get("top_scorers")
        if top_scorers and isinstance(top_scorers.get("extra"), dict):
            rows = top_scorers["extra"].get("rows") or []
            if len(rows) >= 2:
                scope = top_scorers.get("scope") or "bolivia"
                source_id = top_scorers.get("source_id", "")
                for row in rows[1:]:
                    rec = _row_to_record(rows[0], row, TOP_SCORERS_MAP)
                    if not rec.get("jugador"):
                        continue
                    rec.update({"competition": competition, "scope": scope, "source_id": source_id})
                    top_scorers_rows.append(rec)

        assists = blocks.get("assists")
        if assists and isinstance(assists.get("extra"), dict):
            rows = assists["extra"].get("rows") or []
            if len(rows) >= 2:
                scope = assists.get("scope") or "bolivia"
                source_id = assists.get("source_id", "")
                for row in rows[1:]:
                    rec = _row_to_record(rows[0], row, ASSISTS_MAP)
                    if not rec.get("jugador"):
                        continue
                    rec.update({"competition": competition, "scope": scope, "source_id": source_id})
                    assists_rows.append(rec)

        matches = blocks.get("matches")
        if matches and isinstance(matches.get("extra"), dict):
            header = matches["extra"].get("header") or []
            rows = matches["extra"].get("rows") or []
            scope = matches.get("scope") or "bolivia"
            source_id = matches.get("source_id", "")
            for row in rows:
                rec = _row_to_record(header, row, MATCHES_MAP)
                if not rec.get("local") or not rec.get("visitante"):
                    continue
                resultado = rec.get("resultado", "") or "–"
                score_m = re.match(r"\s*(\d+)\s*[–\-:]\s*(\d+)", resultado)
                rec.update({
                    "id": f"{competition}:{rec.get('fecha','')}:{rec['local']}:{rec['visitante']}"[:200],
                    "competition": competition,
                    "scope": scope,
                    "source_id": source_id,
                    "resultado": resultado,
                    "home_score": int(score_m.group(1)) if score_m else None,
                    "away_score": int(score_m.group(2)) if score_m else None,
                    "jugado": bool(score_m),
                    "local_logo": logo_map.get(_normalize_team_key(rec["local"]), rec.get("local_logo", "")),
                    "visitante_logo": logo_map.get(_normalize_team_key(rec["visitante"]), rec.get("visitante_logo", "")),
                })
                matches_rows.append(rec)

    _upsert(client, "standings", _dedupe_rows(standings_rows, ("competition", "equipo")), on_conflict="competition,equipo")
    _upsert(client, "top_scorers", _dedupe_rows(top_scorers_rows, ("competition", "jugador")), on_conflict="competition,jugador")
    _upsert(client, "assists", _dedupe_rows(assists_rows, ("competition", "jugador")), on_conflict="competition,jugador")
    _upsert(client, "matches", _dedupe_rows(matches_rows, ("id",)), on_conflict="id")


# Tope de escudos nuevos que se suben POR CORRIDA. Con ~150 equipos, subir
# todos de una vez cada hora es lo que estuvo saturando el proyecto Free de
# Supabase (varias corridas seguidas, cada una reintentando ~150 subidas,
# terminaron tumbando el schema cache de PostgREST por varios minutos). Con
# un lote chico, cada corrida sube unos pocos y en unas horas quedan todos,
# sin sobrecargar nada de una sola vez.
MAX_LOGOS_PER_RUN = 15


def sync_team_logos(client, team_assets: dict[str, Any]) -> dict[str, str]:
    """Descarga el escudo real de cada equipo (si lo hay) y lo sube a Supabase Storage,
    para dejar de depender de que la URL original (Wikipedia/FBF/etc.) siga viva.
    Devuelve {team_key: url_publica_en_storage}, solo para equipos subidos con éxito.
    Los equipos sin escudo real (badge_type != club_logo, o sea solo bandera) no se suben:
    se deja que la app siga usando display_badge_url tal cual viene del JSON/columna."""
    try:
        existing = client.schema("futbol_boliviano").table("team_logos").select("team_key,logo_url,source_url").execute()
        known = {row["team_key"]: row for row in (existing.data or [])}
    except Exception as exc:
        # Si ni siquiera esto responde, Supabase está con problemas ahora
        # mismo: mejor no insistir en esta corrida (ya vimos que reintentar
        # con ~150 equipos sin saber cuáles ya están subidos solo empeora
        # las cosas). Se reintenta solo en la próxima corrida programada.
        print(f"supabase_sync: team_logos no responde, se salta la subida de escudos esta corrida: {exc}", flush=True)
        return {}

    result: dict[str, str] = {row["team_key"]: row["logo_url"] for row in known.values() if row.get("logo_url")}
    uploaded_this_run = 0
    for team_key, asset in team_assets.items():
        if uploaded_this_run >= MAX_LOGOS_PER_RUN:
            break
        if asset.get("badge_type") != "club_logo" or not asset.get("logo_url"):
            continue
        source_url = asset["logo_url"]
        prev = known.get(team_key)
        if prev and prev.get("source_url") == source_url and prev.get("logo_url"):
            continue
        try:
            _logo_download_throttle()
            resp = requests.get(source_url, timeout=15, headers={"User-Agent": LOGO_USER_AGENT})
            resp.raise_for_status()
            original_content_type = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
            image_bytes, content_type = _remove_solid_background(resp.content, original_content_type)
            ext = mimetypes.guess_extension(content_type) or ".png"
            path = f"{team_key.replace(' ', '_')}{ext}"
            # Sin reintentos aquí a propósito: si Storage está con problemas
            # (503/PGRST002), insistir 2-3 veces más por CADA equipo es lo
            # que alargaba la corrida a 15+ minutos sin lograr nada. Mejor
            # fallar rápido y que ese equipo se reintente en la próxima
            # corrida (30-60 min después), no en la misma.
            client.storage.from_(LOGO_BUCKET).upload(
                path, image_bytes, {"content-type": content_type, "upsert": "true"}
            )
            public_url = client.storage.from_(LOGO_BUCKET).get_public_url(path)
            if isinstance(public_url, dict):
                # Algunas versiones de storage3 devuelven {"publicUrl": "..."} en vez de un str.
                public_url = public_url.get("publicUrl") or public_url.get("publicURL") or ""
            client.schema("futbol_boliviano").table("team_logos").upsert({
                "team_key": team_key,
                "name": asset.get("name", ""),
                "country": asset.get("country", ""),
                "source_url": source_url,
                "storage_path": path,
                "logo_url": public_url,
            }, on_conflict="team_key").execute()
            result[team_key] = public_url
            uploaded_this_run += 1
            print(f"supabase_sync: escudo subido -> {team_key} ({uploaded_this_run}/{MAX_LOGOS_PER_RUN})", flush=True)
        except Exception as exc:
            print(f"supabase_sync: ERROR subiendo escudo de {team_key}: {type(exc).__name__}: {exc}", flush=True)
    return result


def sync_manual_logos(client) -> dict[str, str]:
    """Sube los escudos que se pusieron a mano en manual_logos/ (equipos que
    Wikidata/Wikipedia/TheSportsDB nunca van a tener, ej. clubes amateurs
    bolivianos chicos). El nombre de archivo es el nombre del equipo con
    espacios como "_" (ej. "real_potosi.png"); se re-normaliza igual que
    cualquier otro nombre de equipo para calzar sin importar tildes/mayúsculas."""
    if not MANUAL_LOGOS_DIR.is_dir():
        return {}
    result: dict[str, str] = {}
    for path in sorted(MANUAL_LOGOS_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
            continue
        team_key = _normalize_team_key(path.stem.replace("_", " "))
        if not team_key:
            continue
        try:
            original_content_type = mimetypes.guess_type(path.name)[0] or "image/png"
            image_bytes, content_type = _remove_solid_background(path.read_bytes(), original_content_type)
            ext = mimetypes.guess_extension(content_type) or path.suffix
            storage_path = f"manual_{path.stem}{ext}"
            client.storage.from_(LOGO_BUCKET).upload(
                storage_path, image_bytes, {"content-type": content_type, "upsert": "true"}
            )
            public_url = client.storage.from_(LOGO_BUCKET).get_public_url(storage_path)
            if isinstance(public_url, dict):
                public_url = public_url.get("publicUrl") or public_url.get("publicURL") or ""
            client.schema("futbol_boliviano").table("team_logos").upsert({
                "team_key": team_key,
                "name": path.stem.replace("_", " ").title(),
                "country": "Bolivia",
                "source_url": "manual",
                "storage_path": storage_path,
                "logo_url": public_url,
            }, on_conflict="team_key").execute()
            result[team_key] = public_url
            print(f"supabase_sync: escudo manual subido -> {team_key}", flush=True)
        except Exception as exc:
            print(f"supabase_sync: ERROR subiendo escudo manual {path.name}: {type(exc).__name__}: {exc}", flush=True)
    return result


def sync(items: list[dict[str, Any]], current_tables: dict[str, Any]) -> None:
    client = _get_client()
    if client is None:
        print("supabase_sync: SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY no configurados, se omite.", flush=True)
        return
    push_items(client, items)
    manual_logo_map = sync_manual_logos(client)
    logo_map = sync_team_logos(client, current_tables.get("team_assets") or {})
    logo_map.update(manual_logo_map)  # los manuales ganan si hay choque
    push_current_tables(client, current_tables, logo_map)
