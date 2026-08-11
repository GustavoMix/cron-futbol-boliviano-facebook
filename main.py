from __future__ import annotations


# ===== scraper/models.py =====

from dataclasses import dataclass, asdict, field
from typing import Any, Optional


@dataclass
class Item:
    id: str
    kind: str
    title: str
    text: str = ""
    url: str = ""
    image_url: str = ""
    published_at: Optional[str] = None
    scraped_at: Optional[str] = None
    source_id: str = ""
    source_name: str = ""
    source_type: str = ""
    source_authority: float = 0.5
    scope: str = "general"
    competition: str = "general"
    rank_score: float = 0.0
    stale: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ===== scraper/http.py =====

import os
import time
from typing import Any

import requests


class HttpClient:
    def __init__(self, user_agent: str, timeout: int | None = None):
        self.timeout = timeout or int(os.getenv("HTTP_TIMEOUT", "25"))
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept-Language": "es-BO,es;q=0.9,en;q=0.5",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        })

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        last_exc = None
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=self.timeout, **kwargs)
                if r.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                return r
            except requests.RequestException as exc:
                last_exc = exc
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise last_exc  # type: ignore[misc]


# ===== scraper/utils.py =====

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import urljoin, urlparse

import dateparser
from dateparser.search import search_dates


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def stable_id(*parts: str) -> str:
    raw = "|".join((p or "").strip() for p in parts)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip()


def strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value) if not unicodedata.combining(c))


def normalize_title(value: str) -> str:
    value = strip_accents(clean_text(value).lower())
    value = re.sub(r"https?://\S+", "", value)
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def absolute_url(base: str, maybe_url: str) -> str:
    if not maybe_url:
        return ""
    return urljoin(base, maybe_url)


def domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def parse_date(value: Any, languages: Optional[list[str]] = None) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = clean_text(str(value))
        if not text:
            return None
        dt = dateparser.parse(
            text,
            languages=languages,
            settings={
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TO_TIMEZONE": "UTC",
                "PREFER_DATES_FROM": "past",
            },
        )
        if dt is None and len(text) < 180:
            found = search_dates(
                text,
                languages=languages,
                settings={"RETURN_AS_TIMEZONE_AWARE": True, "TO_TIMEZONE": "UTC", "PREFER_DATES_FROM": "past"},
            )
            if found:
                dt = found[-1][1]
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def json_dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def flatten(items: Iterable[Iterable[Any]]) -> list[Any]:
    out: list[Any] = []
    for group in items:
        out.extend(group)
    return out


# ===== scraper/classifier.py =====



RULES: list[tuple[str, tuple[str, ...]]] = [
    ("libertadores", ("libertadores",)),
    ("sudamericana", ("sudamericana",)),
    ("simon_bolivar", ("simon bolivar", "copa simon bolivar")),
    ("copa_division_profesional", ("copa pacena", "copa de la division profesional")),
    ("sub19", ("sub 19", "sub19", "u19")),
    ("sub16", ("sub 16", "sub16", "u16")),
    ("femenino", ("femenina", "femenino", "women", "women's")),
    ("seleccion_bolivia", ("la verde", "seleccion boliviana", "seleccion de bolivia", "bolivia vs", "bolivia v ")),
    ("concacaf_champions_cup", ("concacaf champions cup", "champions cup")),
    ("concacaf_nations_league", ("concacaf nations league", "liga de naciones concacaf")),
    ("mundial", ("world cup", "copa mundial", "mundial 2026")),
    ("division_profesional", ("division profesional", "liga profesional bolivia", "liga 1xbet")),
]


def classify(item: Item) -> None:
    probe = normalize_title(f"{item.title} {item.text}")
    tags: list[str] = []
    for competition, terms in RULES:
        if any(term in probe for term in terms):
            tags.append(competition)
    if tags:
        item.extra.setdefault("tags", [])
        item.extra["tags"] = sorted(set(item.extra["tags"] + tags))
        # Solo reemplaza etiquetas demasiado genéricas. Una fuente dedicada conserva su competición.
        if item.competition in {"general", "clubes_bolivia_internacional"}:
            item.competition = tags[0]


# ===== scraper/freshness.py =====

import math
from datetime import datetime, timezone
from typing import Optional

from rapidfuzz.fuzz import ratio



def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def freshness_value(published_at: Optional[str], half_life_hours: float = 36.0) -> float:
    dt = _parse_iso(published_at)
    if not dt:
        return 0.20
    age_h = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0)
    return max(0.0, min(1.0, math.pow(0.5, age_h / half_life_hours)))


def rank_item(item: Item) -> float:
    # Noticias/social: frescura manda. Datos estructurados: autoridad manda.
    if item.kind in {"news", "social", "video"}:
        f = freshness_value(item.published_at, half_life_hours=30.0)
        score = 0.72 * f + 0.28 * item.source_authority
    else:
        f = freshness_value(item.published_at, half_life_hours=168.0)
        score = 0.25 * f + 0.75 * item.source_authority
    return round(score, 6)


def mark_stale(item: Item, max_days: int) -> None:
    dt = _parse_iso(item.published_at)
    if not dt:
        item.stale = False
        return
    age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
    item.stale = age_days > max_days


def dedupe(items: list[Item], threshold: int = 90) -> list[Item]:
    # Conserva la versión mejor puntuada y registra URLs alternativas en extra.related_sources.
    ranked = sorted(items, key=lambda x: (x.rank_score, x.published_at or ""), reverse=True)
    kept: list[Item] = []
    normalized: list[str] = []
    for item in ranked:
        key = normalize_title(item.title or item.text[:160])
        if not key:
            kept.append(item)
            normalized.append("")
            continue
        duplicate_idx = None
        for i, existing in enumerate(normalized):
            if existing and ratio(key, existing) >= threshold:
                duplicate_idx = i
                break
        if duplicate_idx is None:
            item.extra.setdefault("related_sources", [])
            kept.append(item)
            normalized.append(key)
        else:
            primary = kept[duplicate_idx]
            primary.extra.setdefault("related_sources", []).append({
                "source_name": item.source_name,
                "url": item.url,
                "published_at": item.published_at,
            })
    return kept


# ===== scraper/providers/facebook.py =====

import os
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote



def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def scrape_facebook(http, cfg: dict[str, Any]) -> tuple[list[Item], list[str]]:
    token = os.getenv("META_ACCESS_TOKEN", "").strip()
    version = os.getenv("META_GRAPH_VERSION", "v26.0").strip() or "v26.0"
    if not cfg.get("enabled", False):
        return [], []
    if not token:
        return [], ["Facebook omitido: falta META_ACCESS_TOKEN."]

    base = f"https://graph.facebook.com/{version}"
    out: list[Item] = []
    errors: list[str] = []
    for spec in cfg.get("page_queries", []):
        name = spec["name"]
        try:
            # Requiere Page Public Content Access para consultar páginas ajenas.
            search_url = f"{base}/pages/search"
            sr = http.get(search_url, params={"q": name, "fields": "id,name,link", "limit": 10, "access_token": token}).json()
            candidates = sr.get("data", [])
            if not candidates:
                errors.append(f"Facebook: no se encontró página para {name!r}.")
                continue
            page = max(candidates, key=lambda p: _similarity(name, p.get("name", "")))
            page_id = page["id"]
            fields = "id,message,created_time,permalink_url,full_picture,attachments{media_type,url,title,description}"
            pr = http.get(f"{base}/{page_id}/posts", params={"fields": fields, "limit": 50, "access_token": token}).json()
            for post in pr.get("data", []):
                message = clean_text(post.get("message", ""))
                att_data = (post.get("attachments") or {}).get("data") or []
                att_title = clean_text(att_data[0].get("title", "")) if att_data else ""
                title = message[:180] if message else att_title
                if not title:
                    continue
                url = post.get("permalink_url", "")
                out.append(Item(
                    id=stable_id("facebook", post.get("id", "")), kind="social", title=title, text=message,
                    url=url, image_url=post.get("full_picture", ""), published_at=parse_date(post.get("created_time")),
                    scraped_at=utc_now_iso(), source_id=f"facebook:{page_id}",
                    source_name=f"Facebook · {page.get('name', name)}", source_type="facebook",
                    source_authority=float(spec.get("authority", 0.85)), scope=spec.get("scope", "general"),
                    competition=spec.get("competition", "general"), extra={"page_id": page_id, "page_name": page.get("name")},
                ))
        except Exception as exc:
            errors.append(f"Facebook {name}: {type(exc).__name__}: {exc}")
    return out, errors


# ===== scraper/providers/x_api.py =====

import os
from typing import Any



def scrape_x(http, cfg: dict[str, Any], limit: int = 50) -> tuple[list[Item], list[str]]:
    token = os.getenv("X_BEARER_TOKEN", "").strip()
    if not cfg.get("enabled", False):
        return [], []
    if not token:
        return [], ["X omitido: falta X_BEARER_TOKEN."]
    out: list[Item] = []
    errors: list[str] = []
    headers = {"Authorization": f"Bearer {token}"}
    for spec in cfg.get("queries", []):
        query = spec["query"]
        try:
            params = {
                "query": query,
                "max_results": max(10, min(100, limit)),
                "sort_order": "recency",
                "tweet.fields": "created_at,lang,public_metrics,author_id,attachments",
                "expansions": "author_id,attachments.media_keys",
                "user.fields": "name,username,profile_image_url,verified",
                "media.fields": "url,preview_image_url,type,width,height",
            }
            data = http.get("https://api.x.com/2/tweets/search/recent", params=params, headers=headers).json()
            users = {u["id"]: u for u in data.get("includes", {}).get("users", [])}
            media = {m["media_key"]: m for m in data.get("includes", {}).get("media", [])}
            for post in data.get("data", []):
                text = clean_text(post.get("text", ""))
                if not text:
                    continue
                user = users.get(post.get("author_id", ""), {})
                username = user.get("username", "")
                url = f"https://x.com/{username}/status/{post['id']}" if username else f"https://x.com/i/web/status/{post['id']}"
                image = ""
                for key in post.get("attachments", {}).get("media_keys", []):
                    m = media.get(key, {})
                    image = m.get("url") or m.get("preview_image_url") or image
                    if image:
                        break
                authority = float(spec.get("authority", 0.7))
                if user.get("verified"):
                    authority = min(0.92, authority + 0.08)
                out.append(Item(
                    id=stable_id("x", post["id"]), kind="social", title=text[:180], text=text, url=url,
                    image_url=image, published_at=parse_date(post.get("created_at")), scraped_at=utc_now_iso(),
                    source_id=f"x:{username or post.get('author_id','')}",
                    source_name=f"X · @{username}" if username else "X", source_type="x",
                    source_authority=authority, scope=spec.get("scope", "general"),
                    competition=spec.get("competition", "general"), extra={"user": user, "metrics": post.get("public_metrics", {})},
                ))
        except Exception as exc:
            errors.append(f"X query {query!r}: {type(exc).__name__}: {exc}")
    return out, errors


# ===== scraper/providers/youtube.py =====

import os
from datetime import datetime, timedelta, timezone
from typing import Any



def scrape_youtube(http, cfg: dict[str, Any], max_results: int = 25) -> tuple[list[Item], list[str]]:
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not cfg.get("enabled", False):
        return [], []
    if not key:
        return [], ["YouTube omitido: falta YOUTUBE_API_KEY."]
    out: list[Item] = []
    errors: list[str] = []
    published_after = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat().replace("+00:00", "Z")
    for spec in cfg.get("queries", []):
        q = spec["query"]
        try:
            params = {
                "part": "snippet", "q": q, "type": "video", "order": "date",
                "maxResults": max(1, min(50, max_results)), "regionCode": "BO",
                "relevanceLanguage": "es", "publishedAfter": published_after, "key": key,
            }
            data = http.get("https://www.googleapis.com/youtube/v3/search", params=params).json()
            for row in data.get("items", []):
                vid = row.get("id", {}).get("videoId")
                sn = row.get("snippet", {})
                if not vid:
                    continue
                title = clean_text(sn.get("title", ""))
                thumbs = sn.get("thumbnails", {})
                image = (thumbs.get("high") or thumbs.get("medium") or thumbs.get("default") or {}).get("url", "")
                out.append(Item(
                    id=stable_id("youtube", vid), kind="video", title=title,
                    text=clean_text(sn.get("description", "")), url=f"https://www.youtube.com/watch?v={vid}",
                    image_url=image, published_at=parse_date(sn.get("publishedAt")), scraped_at=utc_now_iso(),
                    source_id=f"youtube:{sn.get('channelId','')}", source_name=f"YouTube · {sn.get('channelTitle','')}",
                    source_type="youtube", source_authority=float(spec.get("authority", 0.65)),
                    scope=spec.get("scope", "general"), competition=spec.get("competition", "general"),
                    extra={"channel_id": sn.get("channelId", "")},
                ))
        except Exception as exc:
            errors.append(f"YouTube query {q!r}: {type(exc).__name__}: {exc}")
    return out, errors


# ===== scraper/providers/web_generic.py =====

import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag



NEWS_HINTS = ("noticia", "news", "prensa", "article", "post")
TABLE_HINTS = ("posicion", "posición", "clasificacion", "clasificación", "tabla", "standings")
SCORER_HINTS = ("goleador", "goleadores", "scorer", "scorers")
MATCH_HINTS = ("partido", "partidos", "fixture", "resultado", "resultados", "fecha")


def _find_image(node: Tag, base_url: str) -> str:
    img = node.find("img")
    if not img:
        return ""
    src = img.get("data-src") or img.get("data-lazy-src") or img.get("src") or ""
    return absolute_url(base_url, str(src))


def _find_time(node: Tag) -> str | None:
    t = node.find("time")
    if t:
        raw = t.get("datetime") or t.get_text(" ", strip=True)
        parsed = parse_date(raw, languages=["es", "en"])
        if parsed:
            return parsed
    # Solo intenta fechas explícitas; evita confundir marcadores como 3-0 con fechas.
    text = clean_text(node.get_text(" ", strip=True))[:300]
    date_patterns = [
        r"\b\d{4}-\d{1,2}-\d{1,2}\b",
        r"\b\d{1,2}[/-]\d{1,2}[/-]\d{4}\b",
        r"\b\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)(?:\s+de\s+\d{4})?\b",
        r"\b(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)\s+\d{1,2},?\s+\d{4}\b",
    ]
    for pattern in date_patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            parsed = parse_date(m.group(0), languages=["es", "en"])
            if parsed:
                return parsed
    return None


def extract_jsonld(soup: BeautifulSoup, source: dict[str, Any], base_url: str) -> list[Item]:
    out: list[Item] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        nodes = data if isinstance(data, list) else [data]
        expanded: list[Any] = []
        for n in nodes:
            if isinstance(n, dict) and isinstance(n.get("@graph"), list):
                expanded.extend(n["@graph"])
            else:
                expanded.append(n)
        for obj in expanded:
            if not isinstance(obj, dict):
                continue
            typ = obj.get("@type")
            types = set(typ if isinstance(typ, list) else [typ])
            if types.intersection({"NewsArticle", "Article", "BlogPosting"}):
                title = clean_text(str(obj.get("headline") or obj.get("name") or ""))
                if not title:
                    continue
                url = obj.get("url") or obj.get("mainEntityOfPage") or base_url
                if isinstance(url, dict):
                    url = url.get("@id") or base_url
                image = obj.get("image") or ""
                if isinstance(image, list):
                    image = image[0] if image else ""
                if isinstance(image, dict):
                    image = image.get("url") or ""
                published = parse_date(obj.get("datePublished"), languages=["es", "en"])
                out.append(Item(
                    id=stable_id(source["id"], str(url), title), kind="news", title=title,
                    text=clean_text(str(obj.get("description") or "")), url=absolute_url(base_url, str(url)),
                    image_url=absolute_url(base_url, str(image)), published_at=published, scraped_at=utc_now_iso(),
                    source_id=source["id"], source_name=source["name"], source_type=source.get("source_type", "web"),
                    source_authority=float(source.get("authority", 0.7)), scope=source.get("scope", "general"),
                    competition=source.get("competition", "general"),
                ))
    return out


def extract_news_cards(soup: BeautifulSoup, source: dict[str, Any], base_url: str) -> list[Item]:
    out: list[Item] = []
    nodes: list[Tag] = []
    nodes.extend(soup.find_all("article"))
    if not nodes:
        for selector in [".post", ".news", ".noticia", ".elementor-post", ".blog-post", ".card"]:
            nodes.extend(soup.select(selector))
    seen = set()
    for node in nodes:
        heading = node.find(["h1", "h2", "h3", "h4", "h5"])
        link = (heading.find("a") if heading else None) or node.find("a", href=True)
        title = clean_text((heading or link).get_text(" ", strip=True) if (heading or link) else "")
        if len(title) < 8:
            continue
        href = absolute_url(base_url, str(link.get("href"))) if link and link.get("href") else base_url
        key = (title.lower(), href)
        if key in seen:
            continue
        seen.add(key)
        text = clean_text(node.get_text(" ", strip=True))
        out.append(Item(
            id=stable_id(source["id"], href, title), kind="news", title=title,
            text=text[:1200], url=href, image_url=_find_image(node, base_url), published_at=_find_time(node),
            scraped_at=utc_now_iso(), source_id=source["id"], source_name=source["name"],
            source_type=source.get("source_type", "web"), source_authority=float(source.get("authority", 0.7)),
            scope=source.get("scope", "general"), competition=source.get("competition", "general"),
        ))
    return out


def _heading_before(table: Tag) -> str:
    h = table.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
    return clean_text(h.get_text(" ", strip=True) if h else "")


def extract_tables(soup: BeautifulSoup, source: dict[str, Any], base_url: str) -> list[Item]:
    out: list[Item] = []
    for idx, table in enumerate(soup.find_all("table")):
        rows = []
        for tr in table.find_all("tr"):
            cells = [clean_text(c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
            if cells and any(cells):
                rows.append(cells)
        if len(rows) < 2:
            continue
        heading = _heading_before(table)
        probe = (heading + " " + " ".join(rows[0])).lower()
        kind = "table"
        if any(x in probe for x in SCORER_HINTS):
            kind = "top_scorers"
        elif any(x in probe for x in MATCH_HINTS):
            kind = "matches"
        elif any(x in probe for x in TABLE_HINTS):
            kind = "standings"
        title = heading or f"Tabla {idx + 1}"
        out.append(Item(
            id=stable_id(source["id"], kind, title, str(idx)), kind=kind, title=title, url=base_url,
            published_at=None, scraped_at=utc_now_iso(), source_id=source["id"], source_name=source["name"],
            source_type=source.get("source_type", "web"), source_authority=float(source.get("authority", 0.7)),
            scope=source.get("scope", "general"), competition=source.get("competition", "general"),
            extra={"rows": rows},
        ))
    return out


def extract_scorer_text(soup: BeautifulSoup, source: dict[str, Any], base_url: str) -> list[Item]:
    text = clean_text(soup.get_text(" ", strip=True))
    if "goleador" not in text.lower():
        return []
    matches = list(re.finditer(r"(?P<goals>\d{1,2})\s+Goles?\s+(?P<body>.*?)(?=(?:\d{1,2}\s+Goles?)|$)", text, flags=re.I))
    rows = []
    for m in matches[:30]:
        body = clean_text(m.group("body"))[:500]
        if body:
            rows.append({"goals": int(m.group("goals")), "players_text": body})
    if not rows:
        return []
    return [Item(
        id=stable_id(source["id"], "top_scorers_text"), kind="top_scorers", title="Tabla de goleadores",
        url=base_url, scraped_at=utc_now_iso(), source_id=source["id"], source_name=source["name"],
        source_type=source.get("source_type", "web"), source_authority=float(source.get("authority", 0.7)),
        scope=source.get("scope", "general"), competition=source.get("competition", "general"), extra={"rows": rows},
    )]


def scrape_web_source(http, source: dict[str, Any]) -> list[Item]:
    r = http.get(source["url"])
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    items.extend(extract_jsonld(soup, source, r.url))
    items.extend(extract_news_cards(soup, source, r.url))
    items.extend(extract_tables(soup, source, r.url))
    items.extend(extract_scorer_text(soup, source, r.url))
    # Deduplicación exacta local por ID.
    unique = {x.id: x for x in items}
    return list(unique.values())


# ===== scraper/orchestrator.py =====

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml



DEFAULT_CONFIG_YAML = 'settings:\n  timezone: America/La_Paz\n  max_news_per_source: 40\n  max_social_per_query: 50\n  keep_days_news: 45\n  keep_days_social: 14\n  user_agent: "FutbolBoliviaAggregator/1.0 (+contacto-del-desarrollador)"\n\n# authority: 1.0 = fuente primaria/oficial; valores menores = secundarios.\nweb_sources:\n  - id: fbf_noticias\n    enabled: true\n    name: Federación Boliviana de Fútbol - Noticias\n    url: https://fbf.com.bo/noticias/\n    scope: bolivia\n    competition: general\n    source_type: federation\n    authority: 1.00\n\n  - id: fbf_profesional\n    enabled: true\n    name: FBF - División Profesional\n    url: https://fbf.com.bo/torneos/division-profesional/\n    scope: bolivia\n    competition: division_profesional\n    source_type: federation\n    authority: 1.00\n\n  - id: fbf_copa_pacena\n    enabled: true\n    name: FBF - Copa Paceña\n    url: https://fbf.com.bo/torneos/copa-pacena/\n    scope: bolivia\n    competition: copa_division_profesional\n    source_type: federation\n    authority: 1.00\n\n  - id: fbf_simon_bolivar\n    enabled: true\n    name: FBF - Copa Simón Bolívar\n    url: https://fbf.com.bo/torneos/copa-simon-bolivar/\n    scope: bolivia\n    competition: simon_bolivar\n    source_type: federation\n    authority: 1.00\n\n  - id: fbf_sub19\n    enabled: true\n    name: FBF - Liga Nacional Sub-19\n    url: https://fbf.com.bo/torneos/liga-nacional-sub-19/\n    scope: bolivia\n    competition: sub19\n    source_type: federation\n    authority: 1.00\n\n  - id: fbf_sub16\n    enabled: true\n    name: FBF - Liga Nacional Sub-16\n    url: https://fbf.com.bo/torneos/liga-nacional-sub-16/\n    scope: bolivia\n    competition: sub16\n    source_type: federation\n    authority: 1.00\n\n  - id: conmebol_libertadores\n    enabled: true\n    name: CONMEBOL Libertadores\n    url: https://www.conmebol.com/libertadores/\n    scope: conmebol\n    competition: libertadores\n    source_type: confederation\n    authority: 1.00\n\n  - id: conmebol_sudamericana\n    enabled: true\n    name: CONMEBOL Sudamericana\n    url: https://www.conmebol.com/sudamericana/\n    scope: conmebol\n    competition: sudamericana\n    source_type: confederation\n    authority: 1.00\n\n  - id: conmebol_sub17\n    enabled: true\n    name: CONMEBOL Sub-17\n    url: https://www.conmebol.com/conmebol-sub-17/\n    scope: conmebol\n    competition: conmebol_sub17\n    source_type: confederation\n    authority: 1.00\n\n  - id: fifa_bolivia\n    enabled: true\n    name: FIFA - Bolivia\n    url: https://www.fifa.com/es/search-results?query=Bolivia\n    scope: internacional\n    competition: seleccion_bolivia\n    source_type: federation\n    authority: 1.00\n\n  - id: fifa_tournaments\n    enabled: true\n    name: FIFA - Torneos\n    url: https://www.fifa.com/en/tournaments/\n    scope: internacional\n    competition: fifa\n    source_type: federation\n    authority: 1.00\n\n  - id: fifa_world_cup\n    enabled: true\n    name: FIFA World Cup\n    url: https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026\n    scope: internacional\n    competition: mundial\n    source_type: federation\n    authority: 1.00\n\n  - id: concacaf_champions_cup\n    enabled: true\n    name: Concacaf Champions Cup\n    url: https://www.concacaf.com/competitions/champions-cup\n    scope: internacional\n    competition: concacaf_champions_cup\n    source_type: confederation\n    authority: 1.00\n\n  - id: concacaf_nations_league\n    enabled: true\n    name: Concacaf Nations League\n    url: https://www.concacaf.com/competitions/nations-league\n    scope: internacional\n    competition: concacaf_nations_league\n    source_type: confederation\n    authority: 1.00\n\n# Facebook: requiere META_ACCESS_TOKEN + Page Public Content Access.\n# page_queries usa búsqueda de páginas; el sistema toma los resultados más cercanos al nombre.\nfacebook:\n  enabled: true\n  page_queries:\n    - name: Federación Boliviana de Fútbol\n      scope: bolivia\n      competition: seleccion_bolivia\n      authority: 0.98\n    - name: Club Bolívar\n      scope: bolivia\n      competition: clubes_bolivia\n      authority: 0.92\n    - name: The Strongest\n      scope: bolivia\n      competition: clubes_bolivia\n      authority: 0.92\n    - name: Always Ready\n      scope: bolivia\n      competition: clubes_bolivia\n      authority: 0.90\n    - name: Oriente Petrolero\n      scope: bolivia\n      competition: clubes_bolivia\n      authority: 0.90\n    - name: Blooming\n      scope: bolivia\n      competition: clubes_bolivia\n      authority: 0.90\n    - name: CONMEBOL Libertadores\n      scope: conmebol\n      competition: libertadores\n      authority: 0.98\n    - name: CONMEBOL Sudamericana\n      scope: conmebol\n      competition: sudamericana\n      authority: 0.98\n\n# X: búsqueda reciente (ventana soportada por la API). Agrega más consultas si quieres.\nx:\n  enabled: true\n  queries:\n    - query: \'("fútbol boliviano" OR "futbol boliviano" OR FBF) lang:es -is:retweet\'\n      scope: bolivia\n      competition: general\n      authority: 0.72\n    - query: \'(Bolivia OR "La Verde") (selección OR seleccion) fútbol lang:es -is:retweet\'\n      scope: bolivia\n      competition: seleccion_bolivia\n      authority: 0.72\n    - query: \'(Libertadores OR Sudamericana) (Bolívar OR "The Strongest" OR Bolivia) lang:es -is:retweet\'\n      scope: conmebol\n      competition: clubes_bolivia_internacional\n      authority: 0.72\n\n# YouTube: útil para ruedas de prensa, goles, resúmenes y noticias recientes.\nyoutube:\n  enabled: true\n  queries:\n    - query: futbol boliviano\n      scope: bolivia\n      competition: general\n      authority: 0.68\n    - query: selección boliviana fútbol\n      scope: bolivia\n      competition: seleccion_bolivia\n      authority: 0.68\n    - query: Copa Libertadores Bolivia\n      scope: conmebol\n      competition: libertadores\n      authority: 0.68\n    - query: Copa Sudamericana Bolivia\n      scope: conmebol\n      competition: sudamericana\n      authority: 0.68\n'

def load_config(path: Path) -> dict[str, Any]:
    if path.exists():
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    return yaml.safe_load(DEFAULT_CONFIG_YAML)


def _serialize(items: list[Item]) -> list[dict[str, Any]]:
    return [x.to_dict() for x in items]


def _bucket(items: list[Item], scope: str) -> dict[str, Any]:
    filtered = [x for x in items if x.scope == scope]
    by_kind: dict[str, list[Item]] = defaultdict(list)
    by_comp: dict[str, list[Item]] = defaultdict(list)
    for x in filtered:
        by_kind[x.kind].append(x)
        by_comp[x.competition].append(x)
    for group in by_kind.values():
        group.sort(key=lambda z: (z.rank_score, z.published_at or ""), reverse=True)
    return {
        "scope": scope,
        "generated_at": utc_now_iso(),
        "news": _serialize(by_kind.get("news", [])),
        "social": _serialize(by_kind.get("social", [])),
        "videos": _serialize(by_kind.get("video", [])),
        "standings": _serialize(by_kind.get("standings", [])),
        "top_scorers": _serialize(by_kind.get("top_scorers", [])),
        "matches": _serialize(by_kind.get("matches", [])),
        "tables": _serialize(by_kind.get("table", [])),
        "competitions": {k: _serialize(sorted(v, key=lambda z: (z.rank_score, z.published_at or ""), reverse=True)) for k, v in by_comp.items()},
    }


def run(config_path: Path, output_dir: Path) -> dict[str, Any]:
    cfg = load_config(config_path)
    settings = cfg.get("settings", {})
    http = HttpClient(settings.get("user_agent", "FutbolBoliviaAggregator/1.0"))
    items: list[Item] = []
    errors: list[dict[str, str]] = []
    source_status: list[dict[str, Any]] = []

    for source in cfg.get("web_sources", []):
        if not source.get("enabled", True):
            continue
        try:
            got = scrape_web_source(http, source)
            items.extend(got)
            source_status.append({"id": source["id"], "name": source["name"], "ok": True, "items": len(got)})
        except Exception as exc:
            errors.append({"source": source["id"], "error": f"{type(exc).__name__}: {exc}"})
            source_status.append({"id": source["id"], "name": source["name"], "ok": False, "items": 0})

    fb, fb_errors = scrape_facebook(http, cfg.get("facebook", {}))
    items.extend(fb)
    errors.extend({"source": "facebook", "error": e} for e in fb_errors)

    xs, x_errors = scrape_x(http, cfg.get("x", {}), int(settings.get("max_social_per_query", 50)))
    items.extend(xs)
    errors.extend({"source": "x", "error": e} for e in x_errors)

    yt, yt_errors = scrape_youtube(http, cfg.get("youtube", {}), 25)
    items.extend(yt)
    errors.extend({"source": "youtube", "error": e} for e in yt_errors)

    for item in items:
        classify(item)
        item.rank_score = rank_item(item)
        max_days = int(settings.get("keep_days_social", 14) if item.kind in {"social", "video"} else settings.get("keep_days_news", 45))
        mark_stale(item, max_days)

    # No se eliminan datos oficiales viejos estructurados; sí se filtran noticias/social viejos.
    live: list[Item] = []
    for item in items:
        if item.kind in {"news", "social", "video"} and item.stale:
            continue
        live.append(item)
    live = dedupe(live, threshold=91)
    live.sort(key=lambda z: (z.rank_score, z.published_at or ""), reverse=True)

    output_dir.mkdir(parents=True, exist_ok=True)
    buckets = {
        "bolivia.json": _bucket(live, "bolivia"),
        "conmebol.json": _bucket(live, "conmebol"),
        "internacional.json": _bucket(live, "internacional"),
    }
    social_items = [x for x in live if x.kind in {"social", "video"}]
    social_data = {
        "scope": "social",
        "generated_at": utc_now_iso(),
        "items": _serialize(social_items),
    }
    buckets["social.json"] = social_data

    latest_items = [x for x in live if x.kind in {"news", "social", "video"}]
    latest_items.sort(key=lambda z: (z.rank_score, z.published_at or ""), reverse=True)
    buckets["latest.json"] = {
        "scope": "latest",
        "generated_at": utc_now_iso(),
        "items": _serialize(latest_items[:200]),
    }

    for name, payload in buckets.items():
        json_dump(output_dir / name, payload)

    manifest = {
        "schema_version": 3,
        "generated_at": utc_now_iso(),
        "timezone": settings.get("timezone", "America/La_Paz"),
        "ranking_policy": {
            "news_social": "72% frescura + 28% autoridad de fuente",
            "structured_data": "25% frescura + 75% autoridad de fuente",
            "dates": "published_at = fecha original; scraped_at = fecha de captura",
        },
        "files": {name: {"items": sum(len(v) for k, v in payload.items() if isinstance(v, list))} for name, payload in buckets.items()},
        "source_status": source_status,
        "errors": errors,
        "totals": {
            "items_before_filter": len(items),
            "items_after_filter_dedupe": len(live),
            "web_sources_ok": sum(1 for x in source_status if x["ok"]),
            "web_sources_error": sum(1 for x in source_status if not x["ok"]),
            "social_items": len(social_items),
        },
    }
    json_dump(output_dir / "manifest.json", manifest)
    return manifest


# ===== EJECUCION =====
import argparse
from dotenv import load_dotenv


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(
        description="Agregador fútbol boliviano + CONMEBOL + redes sociales (modo fácil)"
    )
    parser.add_argument("--config", default="sources.yaml")
    parser.add_argument("--output", default=".")
    args = parser.parse_args()

    manifest = run(Path(args.config), Path(args.output))
    print(json.dumps(manifest["totals"], ensure_ascii=False, indent=2))
    if manifest["errors"]:
        print(f"Advertencias/errores: {len(manifest['errors'])}. Ver manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
