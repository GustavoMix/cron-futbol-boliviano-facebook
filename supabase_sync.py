from __future__ import annotations

import mimetypes
import os
import re
import unicodedata
from typing import Any

import requests

LOGO_BUCKET = "team-logos"

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
            record[col] = int(m.group(0)) if m else 0
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
        client.schema("futbol_boliviano").table(table).upsert(rows, on_conflict=on_conflict).execute()
        print(f"supabase_sync: {table} <- {len(rows)} filas", flush=True)
    except Exception as exc:
        print(f"supabase_sync: ERROR en {table}: {type(exc).__name__}: {exc}", flush=True)


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

    _upsert(client, "standings", standings_rows, on_conflict="competition,equipo")
    _upsert(client, "top_scorers", top_scorers_rows, on_conflict="competition,jugador")
    _upsert(client, "assists", assists_rows, on_conflict="competition,jugador")
    _upsert(client, "matches", matches_rows, on_conflict="id")


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
        print(f"supabase_sync: no se pudo leer team_logos existentes: {exc}", flush=True)
        known = {}

    result: dict[str, str] = {}
    for team_key, asset in team_assets.items():
        if asset.get("badge_type") != "club_logo" or not asset.get("logo_url"):
            continue
        source_url = asset["logo_url"]
        prev = known.get(team_key)
        if prev and prev.get("source_url") == source_url and prev.get("logo_url"):
            result[team_key] = prev["logo_url"]
            continue
        try:
            resp = requests.get(source_url, timeout=15, headers={"User-Agent": "FutbolBoliviaAggregator/1.0"})
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "image/png").split(";")[0].strip()
            ext = mimetypes.guess_extension(content_type) or ".png"
            path = f"{team_key.replace(' ', '_')}{ext}"
            client.storage.from_(LOGO_BUCKET).upload(
                path, resp.content, {"content-type": content_type, "upsert": "true"}
            )
            public_url = client.storage.from_(LOGO_BUCKET).get_public_url(path)
            client.schema("futbol_boliviano").table("team_logos").upsert({
                "team_key": team_key,
                "name": asset.get("name", ""),
                "country": asset.get("country", ""),
                "source_url": source_url,
                "storage_path": path,
                "logo_url": public_url,
            }, on_conflict="team_key").execute()
            result[team_key] = public_url
            print(f"supabase_sync: escudo subido -> {team_key}", flush=True)
        except Exception as exc:
            print(f"supabase_sync: ERROR subiendo escudo de {team_key}: {type(exc).__name__}: {exc}", flush=True)
    return result


def sync(items: list[dict[str, Any]], current_tables: dict[str, Any]) -> None:
    client = _get_client()
    if client is None:
        print("supabase_sync: SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY no configurados, se omite.", flush=True)
        return
    push_items(client, items)
    logo_map = sync_team_logos(client, current_tables.get("team_assets") or {})
    push_current_tables(client, current_tables, logo_map)
