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
    video_url: str = ""
    thumbnail_url: str = ""
    media_type: str = "none"
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
    # El match de título solo se compara dentro del mismo `kind`: una tabla de
    # posiciones y una de goleadores de la misma página suelen compartir el
    # mismo heading (ej. "Primera División 2026"), y sin este filtro por kind
    # una terminaba "absorbiendo" a la otra como si fueran la misma noticia.
    # Kinds de datos estructurados: se dedupean también por competición, no
    # solo por kind. Sin esto, "Goleadores" de Libertadores choca contra
    # "Goleadores" de División Profesional (mismo título casi exacto, kind
    # igual) y una competición entera se pierde como si fuera "la misma"
    # tabla que otra.
    STRUCTURED_KINDS = {'standings', 'table', 'top_scorers', 'assists', 'own_goals'}
    ranked = sorted(items, key=lambda x: (x.rank_score, x.published_at or ""), reverse=True)
    kept: list[Item] = []
    normalized: list[tuple[str, str]] = []
    for item in ranked:
        # "matches" son muchas tablas pequeñas (una por fecha) con títulos
        # casi idénticos entre sí ("... — Fecha 1" vs "... — Fecha 2"): el
        # ratio de similitud de texto las confunde con duplicados y se
        # pierden fechas enteras del torneo. No tiene sentido dedupear por
        # título contenido tan parecido a propósito.
        if item.kind == "matches":
            kept.append(item)
            normalized.append(("", item.kind))
            continue
        dedupe_kind = f"{item.kind}::{item.competition}" if item.kind in STRUCTURED_KINDS else item.kind
        key = normalize_title(item.title or item.text[:160])
        if not key:
            kept.append(item)
            normalized.append(("", dedupe_kind))
            continue
        duplicate_idx = None
        for i, (existing, existing_kind) in enumerate(normalized):
            if existing and existing_kind == dedupe_kind and ratio(key, existing) >= threshold:
                duplicate_idx = i
                break
        if duplicate_idx is None:
            item.extra.setdefault("related_sources", [])
            kept.append(item)
            normalized.append((key, dedupe_kind))
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


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _fb_public_post_url(href: str) -> bool:
    h = (href or '').lower()
    return any(x in h for x in ('/posts/', '/videos/', '/reel/', 'story_fbid='))


def _fb_clean_public_text(text: str) -> str:
    text = clean_text(text)
    junk = (
        'Log in', 'Iniciar sesión', 'Forgot account', '¿Olvidaste la cuenta?',
        'Create new account', 'Crear cuenta nueva', 'Like Comment Share',
        'Me gusta Comentar Compartir', 'See more', 'Ver más',
    )
    for token in junk:
        text = text.replace(token, ' ')
    return clean_text(text)


def _fb_canonical_url(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
    try:
        parts = urlsplit(url)
        keep = []
        for k, v in parse_qsl(parts.query, keep_blank_values=True):
            if k in {'story_fbid', 'id'}:
                keep.append((k, v))
        return urlunsplit((parts.scheme or 'https', parts.netloc or 'www.facebook.com', parts.path, urlencode(keep), ''))
    except Exception:
        return url


def _scrape_facebook_public_page_http(http, spec: dict[str, Any], progress: str = '') -> tuple[list[Item], list[str]]:
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    name = spec['name']
    page_url = (spec.get('url') or '').strip()
    if not page_url:
        print(f'{progress} HTTP -> {name}: SIN URL', flush=True)
        return [], [f'Facebook HTTP {name}: falta URL de página.']

    targets = [page_url.rstrip('/') + '/?sk=posts', page_url]
    out: list[Item] = []
    errors: list[str] = []
    seen: set[str] = set()

    print(f'{progress} HTTP -> {name}', flush=True)
    for attempt, target in enumerate(targets, start=1):
        try:
            print(f'      intento {attempt}/2 ...', end=' ', flush=True)
            r = http.get(target, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/152 Safari/537.36',
                'Accept-Language': 'es-BO,es;q=0.9,en;q=0.5',
            })
            soup = BeautifulSoup(r.content, 'lxml')
            anchors = [a for a in soup.find_all('a', href=True) if _fb_public_post_url(a.get('href', ''))]
            for a in anchors:
                href = a.get('href', '')
                url = _fb_canonical_url(urljoin('https://www.facebook.com', href))
                if url in seen:
                    continue
                node = a
                best_text = ''
                for _ in range(8):
                    if not getattr(node, 'parent', None):
                        break
                    node = node.parent
                    candidate = _fb_clean_public_text(node.get_text(' ', strip=True))
                    if 35 <= len(candidate) <= 5000:
                        best_text = candidate
                    if len(candidate) > 1000:
                        break
                if len(best_text) < 20:
                    continue
                required = [normalize_title(str(x)) for x in spec.get('keywords', []) if str(x).strip()]
                if required:
                    probe = normalize_title(best_text)
                    if not any(k in probe for k in required):
                        continue
                img = node.find('img') if hasattr(node, 'find') else None
                image = (img.get('src') or img.get('data-src') or '') if img else ''
                out.append(Item(
                    id=stable_id('facebook-public-http', url), kind='social', title=best_text[:180], text=best_text,
                    url=url, image_url=image, published_at=None, scraped_at=utc_now_iso(),
                    source_id=f"facebook_http:{normalize_title(name).replace(' ', '_')}",
                    source_name=f'Facebook · {name}', source_type='facebook_public_http',
                    source_authority=float(spec.get('authority', 0.80)), scope=spec.get('scope', 'general'),
                    competition=spec.get('competition', 'general'),
                    extra={'page_url': page_url, 'collector': 'public_http'},
                ))
                seen.add(url)
            if out:
                print(f'OK ({len(out)} posts)', flush=True)
                break
            print('sin posts visibles', flush=True)
        except Exception as exc:
            print(f'ERROR {type(exc).__name__}', flush=True)
            errors.append(f'Facebook HTTP {name}: {type(exc).__name__}: {exc}')
    if not out:
        print(f'      => HTTP SIN DATOS; pasa al navegador.', flush=True)
    return out, errors


def _scrape_facebook_search_index(http, spec: dict[str, Any], limit: int = 8, progress: str = '') -> tuple[list[Item], list[str]]:
    # Fallback de descubrimiento: consulta el índice público de Bing y conserva solo URLs de Facebook.
    # No sustituye a Graph API para datos oficiales; sirve para localizar posts públicos indexados.
    from urllib.parse import urlsplit, quote_plus
    from xml.etree import ElementTree as ET
    name = spec.get('name', 'Facebook')
    page_url = (spec.get('url') or '').strip()
    print(f'{progress} INDICE -> {name} ...', end=' ', flush=True)
    if not page_url:
        return [], [f'Facebook índice {name}: falta URL.']
    try:
        path = urlsplit(page_url).path.strip('/').split('/')[0]
        if not path:
            return [], [f'Facebook índice {name}: no se pudo obtener slug de página.']
        extra = ' '.join(str(x) for x in spec.get('keywords', [])[:4]) or 'futbol fútbol Bolivia'
        query = f'site:facebook.com/{path} {extra}'
        url = 'https://www.bing.com/search?format=rss&q=' + quote_plus(query)
        r = http.get(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/rss+xml,text/xml,*/*'})
        root = ET.fromstring(r.text)
        out = []
        seen = set()
        for node in root.findall('.//item'):
            link = clean_text(node.findtext('link') or '')
            title = clean_text(node.findtext('title') or '')
            desc = _fb_clean_public_text(node.findtext('description') or '')
            pub = clean_text(node.findtext('pubDate') or '')
            if 'facebook.com' not in link.lower() or not _fb_public_post_url(link):
                continue
            link = _fb_canonical_url(link)
            if link in seen:
                continue
            text = clean_text((title + ' ' + desc).strip())
            if len(text) < 20:
                continue
            out.append(Item(
                id=stable_id('facebook-index', link), kind='social', title=title[:180] or text[:180], text=text,
                url=link, image_url='', published_at=parse_date(pub) if pub else None, scraped_at=utc_now_iso(),
                source_id=f"facebook_index:{normalize_title(name).replace(' ', '_')}",
                source_name=f'Facebook indexado · {name}', source_type='facebook_search_index',
                source_authority=min(float(spec.get('authority', 0.80)), 0.72), scope=spec.get('scope', 'general'),
                competition=spec.get('competition', 'general'),
                extra={'page_url': page_url, 'collector': 'search_index', 'search_engine': 'bing'},
            ))
            seen.add(link)
            if len(out) >= limit:
                break
        if out:
            print(f'OK ({len(out)} posts)', flush=True)
            return out, []
        print('SIN POSTS', flush=True)
        return [], [f'Facebook índice {name}: no encontró posts indexados.']
    except Exception as exc:
        print(f'ERROR {type(exc).__name__}', flush=True)
        return [], [f'Facebook índice {name}: {type(exc).__name__}: {exc}']

def _launch_public_browser(playwright):
    errors = []
    for channel in ('msedge', 'chrome'):
        try:
            return playwright.chromium.launch(
                channel=channel,
                headless=True,
                args=['--disable-notifications', '--disable-popup-blocking'],
            ), channel, errors
        except Exception as exc:
            errors.append(f'{channel}: {type(exc).__name__}: {exc}')
    try:
        return playwright.chromium.launch(
            headless=True,
            args=['--disable-notifications', '--disable-popup-blocking'],
        ), 'playwright-chromium', errors
    except Exception as exc:
        errors.append(f'playwright-chromium: {type(exc).__name__}: {exc}')
    return None, '', errors


def _fb_parse_published_date(raw: str | None) -> str | None:
    # Convierte textos típicos de Facebook (3 min, 11 h, fecha larga) a UTC ISO.
    from datetime import datetime, timedelta, timezone
    raw = clean_text(str(raw or ''))
    if not raw:
        return None
    now_local = datetime.now(timezone(timedelta(hours=-4)))  # Bolivia
    low = raw.lower().strip()
    if low in {'ahora', 'hace un momento', 'just now'}:
        return now_local.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
    m = re.fullmatch(r'(?:hace\s+)?(\d+)\s*(?:min|minuto|minutos)', low)
    if m:
        return (now_local - timedelta(minutes=int(m.group(1)))).astimezone(timezone.utc).isoformat().replace('+00:00','Z')
    m = re.fullmatch(r'(?:hace\s+)?(\d+)\s*(?:h|hora|horas)', low)
    if m:
        return (now_local - timedelta(hours=int(m.group(1)))).astimezone(timezone.utc).isoformat().replace('+00:00','Z')
    m = re.fullmatch(r'(?:hace\s+)?(\d+)\s*(?:d|día|dias|días)', low)
    if m:
        return (now_local - timedelta(days=int(m.group(1)))).astimezone(timezone.utc).isoformat().replace('+00:00','Z')
    if raw.isdigit() and len(raw) >= 9:
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).isoformat().replace('+00:00','Z')
        except Exception:
            pass
    try:
        dt = dateparser.parse(
            raw,
            languages=['es','pt','en'],
            settings={
                'RELATIVE_BASE': now_local,
                'RETURN_AS_TIMEZONE_AWARE': True,
                'TIMEZONE': 'America/La_Paz',
                'TO_TIMEZONE': 'UTC',
                'PREFER_DATES_FROM': 'past',
            },
        )
        if dt:
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone(timedelta(hours=-4)))
            return dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
    except Exception:
        pass
    return None


def _fb_age_hours(published_at: str | None) -> float | None:
    if not published_at:
        return None
    try:
        dt = datetime.fromisoformat(published_at.replace('Z', '+00:00')).astimezone(timezone.utc)
        return round(max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0), 3)
    except Exception:
        return None


def _fb_engagement(text: str) -> dict[str, Any]:
    # Lectura orientativa; Facebook cambia el formato, por eso también conservamos raw_text.
    def _num(raw: str) -> int | None:
        raw = clean_text(raw).lower().replace(' ', '')
        raw = raw.replace('.', '').replace(',', '.')
        mult = 1
        if raw.endswith('mil'):
            mult, raw = 1000, raw[:-3]
        elif raw.endswith('k'):
            mult, raw = 1000, raw[:-1]
        try:
            return int(float(raw) * mult)
        except Exception:
            return None
    out: dict[str, Any] = {}
    patterns = {
        'comments': r'([\d.,]+\s*(?:mil|k)?)\s+(?:comentarios?|comments?)',
        'shares': r'([\d.,]+\s*(?:mil|k)?)\s+(?:compartidos?|veces compartido|shares?)',
    }
    for key, pat in patterns.items():
        m = re.search(pat, text, flags=re.I)
        if m:
            n = _num(m.group(1))
            if n is not None:
                out[key] = n
    return out


def _fb_post_id(url: str) -> str:
    for pat in (r'/posts/([^/?#]+)', r'/reel/([^/?#]+)', r'/videos/([^/?#]+)', r'[?&]story_fbid=([^&#]+)'):
        m = re.search(pat, url or '', flags=re.I)
        if m:
            return m.group(1)
    return stable_id('facebook-url', url)


def _scrape_facebook_public_browser(specs: list[dict[str, Any]], cfg: dict[str, Any]) -> tuple[list[Item], list[str]]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return [], ['Facebook browser: falta Playwright. Ejecuta INSTALAR_DEPENDENCIAS.bat']

    timeout_ms = int(cfg.get('browser_timeout_seconds', 20)) * 1000
    initial_wait_ms = int(cfg.get('browser_wait_ms', 2600))
    scroll_wait_ms = int(cfg.get('scroll_wait_ms', 900))
    scroll_rounds = max(1, int(cfg.get('scroll_rounds', 5)))
    max_posts = max(1, int(cfg.get('max_posts_per_page', 8)))
    recent_hours = max(1, int(cfg.get('recent_hours', 72)))
    out: list[Item] = []
    errors: list[str] = []
    seen: set[str] = set()

    print('\n--- FACEBOOK: NAVEGADOR REAL (Edge/Chrome) ---', flush=True)
    print(f'Máximo {max_posts} posts/página · filtro {recent_hours} h · {scroll_rounds} scrolls', flush=True)
    print('Iniciando navegador ...', end=' ', flush=True)
    with sync_playwright() as p:
        browser, browser_name, launch_errors = _launch_public_browser(p)
        if browser is None:
            print('ERROR', flush=True)
            errors.append('Facebook browser: no se pudo iniciar Edge/Chrome. ' + ' | '.join(launch_errors[-2:]))
            return [], errors
        print(f'OK ({browser_name})', flush=True)
        try:
            context = browser.new_context(locale='es-BO', viewport={'width': 1280, 'height': 1800})
            page = context.new_page()
            total_specs = len(specs)
            for idx, spec in enumerate(specs, start=1):
                name = spec.get('name', 'Facebook')
                page_url = (spec.get('url') or '').strip()
                if not page_url:
                    errors.append(f'Facebook browser {name}: falta URL.')
                    continue
                target = page_url.rstrip('/') + '/?sk=posts'
                print(f'[{idx}/{total_specs}] {name}', flush=True)
                print('      cargando ...', end=' ', flush=True)
                try:
                    page.goto(target, wait_until='domcontentloaded', timeout=timeout_ms)
                    page.wait_for_timeout(initial_wait_ms)
                    print('OK', flush=True)

                    # Cierra/acepta banners de cookies cuando aparecen; si no están, no hace nada.
                    for label in ('Permitir todas las cookies', 'Allow all cookies', 'Aceptar todas las cookies'):
                        try:
                            btn = page.get_by_role('button', name=label)
                            if btn.count() > 0:
                                btn.first.click(timeout=1000)
                                page.wait_for_timeout(500)
                                break
                        except Exception:
                            pass

                    last_height = 0
                    for sr in range(scroll_rounds):
                        try:
                            height = page.evaluate('document.body.scrollHeight')
                            print(f'      scroll {sr+1}/{scroll_rounds} ...', end=' ', flush=True)
                            page.evaluate('window.scrollBy(0, Math.max(1000, window.innerHeight * 0.90))')
                            page.wait_for_timeout(scroll_wait_ms)
                            new_height = page.evaluate('document.body.scrollHeight')
                            print('OK', flush=True)
                            if sr >= 2 and new_height == last_height == height:
                                break
                            last_height = new_height
                        except Exception:
                            print('omitido', flush=True)
                            break

                    records = page.evaluate(r'''() => {
                      const isPost = h => h && (h.includes('/posts/') || h.includes('/videos/') || h.includes('/reel/') || h.includes('story_fbid='));
                      const absolute = h => { try { return new URL(h, location.href).href; } catch(e) { return h || ''; } };
                      let boxes = Array.from(document.querySelectorAll('[role="article"]'));
                      if (!boxes.length) {
                        const links = Array.from(document.querySelectorAll('a[href]')).filter(a => isPost(a.href));
                        boxes = links.map(a => {
                          let n=a;
                          for (let i=0;i<8 && n && n.parentElement;i++) {
                            n=n.parentElement;
                            const t=(n.innerText||'').trim();
                            if (t.length>=60) break;
                          }
                          return n;
                        }).filter(Boolean);
                      }
                      const rows=[]; const used=new Set();
                      for (const box of boxes) {
                        const anchors=Array.from(box.querySelectorAll('a[href]'));
                        const link=anchors.find(a => isPost(a.href));
                        if (!link) continue;
                        const href=absolute(link.href);
                        if (used.has(href)) continue;
                        const text=(box.innerText||'').replace(/\s+/g,' ').trim();
                        if (text.length<20) continue;
                        used.add(href);

                        const dateCandidates=[];
                        for (const el of box.querySelectorAll('abbr,time,a[aria-label],a')) {
                          const raw=(el.getAttribute('datetime')||el.getAttribute('data-utime')||el.getAttribute('aria-label')||el.textContent||'').replace(/\s+/g,' ').trim();
                          if (!raw || raw.length>90) continue;
                          if (/^(ahora|hace un momento|\d+\s*(min|h|d|sem))$/i.test(raw) || /\d{1,2}\s+de\s+[a-záéíóúñ]+/i.test(raw) || /^\d{1,2}\s+[a-z]{3,}/i.test(raw)) dateCandidates.push(raw);
                        }

                        const imageCandidates=[];
                        for (const im of box.querySelectorAll('img[src]')) {
                          const src=im.currentSrc||im.src||'';
                          if (!src || src.startsWith('data:')) continue;
                          const area=(im.naturalWidth||im.width||0)*(im.naturalHeight||im.height||0);
                          if (area < 12000) continue;
                          imageCandidates.push({src, area});
                        }
                        imageCandidates.sort((a,b)=>b.area-a.area);
                        const images=[...new Set(imageCandidates.map(x=>x.src))].slice(0,6);

                        const videos=[];
                        for (const v of box.querySelectorAll('video,video source')) {
                          const src=(v.currentSrc||v.src||v.getAttribute('src')||'').trim();
                          if (src && !src.startsWith('blob:') && !src.startsWith('data:')) videos.push(src);
                        }
                        const posters=Array.from(box.querySelectorAll('video[poster]')).map(v=>v.poster).filter(Boolean);
                        const type = href.includes('/reel/') ? 'reel' : (href.includes('/videos/') || videos.length || box.querySelector('video')) ? 'video' : images.length ? 'image' : 'text';
                        rows.push({href, text, dateText: dateCandidates[0]||'', images, videos:[...new Set(videos)].slice(0,3), posters:[...new Set(posters)].slice(0,3), mediaType:type});
                      }
                      return rows;
                    }''')

                    count_before = len(out)
                    old_skipped = 0
                    for rec in records:
                        url = _fb_canonical_url(str(rec.get('href') or ''))
                        if not url or url in seen:
                            continue
                        text = _fb_clean_public_text(str(rec.get('text') or ''))
                        if len(text) < 20:
                            continue
                        required = [normalize_title(str(x)) for x in spec.get('keywords', []) if str(x).strip()]
                        if required:
                            probe = normalize_title(text)
                            if not any(k in probe for k in required):
                                continue
                        published_raw = clean_text(str(rec.get('dateText') or ''))
                        published = _fb_parse_published_date(published_raw)
                        age_hours = _fb_age_hours(published)
                        if age_hours is not None and age_hours > recent_hours:
                            old_skipped += 1
                            continue

                        images = [str(x) for x in (rec.get('images') or []) if str(x).startswith('http')]
                        videos = [str(x) for x in (rec.get('videos') or []) if str(x).startswith('http') and not str(x).startswith('blob:')]
                        posters = [str(x) for x in (rec.get('posters') or []) if str(x).startswith('http')]
                        media_type = str(rec.get('mediaType') or 'text')
                        thumb = (posters[0] if posters else (images[0] if images else ''))
                        image = images[0] if images else thumb
                        direct_video = videos[0] if videos else ''
                        stable_video_page = url if media_type in {'video','reel'} else ''
                        engagement = _fb_engagement(text)

                        out.append(Item(
                            id=stable_id('facebook-browser', url), kind='social', title=text[:180], text=text,
                            url=url, image_url=image, video_url=direct_video, thumbnail_url=thumb,
                            media_type=media_type, published_at=published, scraped_at=utc_now_iso(),
                            source_id=f"facebook_browser:{normalize_title(name).replace(' ', '_')}",
                            source_name=f'Facebook · {name}', source_type='facebook_browser_public',
                            source_authority=float(spec.get('authority', 0.80)), scope=spec.get('scope', 'general'),
                            competition=spec.get('competition', 'general'),
                            extra={
                                'page_url': page_url,
                                'collector': 'browser_public',
                                'browser': browser_name,
                                'post_id': _fb_post_id(url),
                                'published_raw': published_raw,
                                'age_hours': age_hours,
                                'freshness_unknown': published is None,
                                'media': {
                                    'type': media_type,
                                    'images': images,
                                    'thumbnail_url': thumb,
                                    'direct_video_urls': videos,
                                    'video_post_url': stable_video_page,
                                    'direct_video_url_may_expire': bool(direct_video),
                                },
                                'engagement': engagement,
                            },
                        ))
                        seen.add(url)
                        if len(out) - count_before >= max_posts:
                            break
                    found_now = len(out) - count_before
                    suffix = f' · descartados viejos: {old_skipped}' if old_skipped else ''
                    if found_now:
                        print(f'      => OK: {found_now} posts actuales{suffix}', flush=True)
                    else:
                        print(f'      => SIN POSTS ACTUALES{suffix}', flush=True)
                        body = _fb_clean_public_text(page.locator('body').inner_text(timeout=5000))[:260]
                        if 'iniciar sesión' in body.lower() or 'log in' in body.lower():
                            errors.append(f'Facebook browser {name}: Meta mostró muro de inicio de sesión; no hubo posts públicos visibles.')
                        else:
                            errors.append(f'Facebook browser {name}: página cargó, pero no se detectaron posts actuales visibles.')
                except Exception as exc:
                    print(f'      => ERROR {type(exc).__name__}', flush=True)
                    errors.append(f'Facebook browser {name}: {type(exc).__name__}: {exc}')
            context.close()
        finally:
            browser.close()
    return out, errors

def scrape_facebook(http, cfg: dict[str, Any]) -> tuple[list[Item], list[str]]:
    token = os.getenv('META_ACCESS_TOKEN', '').strip()
    version = os.getenv('META_GRAPH_VERSION', 'v26.0').strip() or 'v26.0'
    if not cfg.get('enabled', False):
        return [], []

    mode = str(cfg.get('mode', 'auto')).strip().lower()
    out: list[Item] = []
    errors: list[str] = []

    if token and mode in {'auto', 'graph', 'both'}:
        base = f'https://graph.facebook.com/{version}'
        for spec in cfg.get('page_queries', []):
            name = spec['name']
            try:
                sr = http.get(f'{base}/pages/search', params={
                    'q': name, 'fields': 'id,name,link', 'limit': 10, 'access_token': token,
                }).json()
                candidates = sr.get('data', [])
                if not candidates:
                    errors.append(f'Facebook Graph: no se encontró página para {name!r}.')
                    continue
                page_data = max(candidates, key=lambda x: _similarity(name, x.get('name', '')))
                page_id = page_data['id']
                fields = 'id,message,created_time,permalink_url,full_picture,attachments{media_type,url,title,description}'
                pr = http.get(f'{base}/{page_id}/posts', params={'fields': fields, 'limit': 50, 'access_token': token}).json()
                for post in pr.get('data', []):
                    message = clean_text(post.get('message', ''))
                    att_data = (post.get('attachments') or {}).get('data') or []
                    att_title = clean_text(att_data[0].get('title', '')) if att_data else ''
                    title = message[:180] if message else att_title
                    if not title:
                        continue
                    out.append(Item(
                        id=stable_id('facebook', post.get('id', '')), kind='social', title=title, text=message,
                        url=post.get('permalink_url', ''), image_url=post.get('full_picture', ''),
                        published_at=parse_date(post.get('created_time')), scraped_at=utc_now_iso(),
                        source_id=f'facebook:{page_id}', source_name=f"Facebook · {page_data.get('name', name)}",
                        source_type='facebook', source_authority=float(spec.get('authority', 0.85)),
                        scope=spec.get('scope', 'general'), competition=spec.get('competition', 'general'),
                        extra={'page_id': page_id, 'page_name': page_data.get('name'), 'collector': 'graph_api'},
                    ))
            except Exception as exc:
                errors.append(f'Facebook Graph {name}: {type(exc).__name__}: {exc}')
        if out and mode == 'auto':
            return out, errors

    specs = cfg.get('public_pages') or cfg.get('page_queries', [])
    if mode in {'auto', 'public', 'both', 'browser'}:
        total = len(specs)
        print(f'Facebook: {total} páginas configuradas.', flush=True)

        # V4: navegador primero. La prueba real mostró HTTP 400 en todas las páginas;
        # por defecto no perdemos tiempo haciendo 2 solicitudes fallidas por fuente.
        got, errs = _scrape_facebook_public_browser(specs, cfg)
        out.extend(got)
        errors.extend(errs)

        pages_with_items = {normalize_title(x.extra.get('page_url', '')) for x in out if x.kind == 'social'}
        pending_specs = [s for s in specs if normalize_title(s.get('url','')) not in pages_with_items]

        # HTTP queda como opción de diagnóstico, apagada por defecto.
        if pending_specs and cfg.get('http_fallback', False):
            print('\n--- FACEBOOK: HTTP DE RESPALDO ---', flush=True)
            total_http = len(pending_specs)
            still_pending = []
            for idx, spec in enumerate(pending_specs, start=1):
                got, errs = _scrape_facebook_public_page_http(http, spec, progress=f'[{idx}/{total_http}]')
                out.extend(got)
                errors.extend(errs)
                if not got:
                    still_pending.append(spec)
            pending_specs = still_pending

        # Último respaldo: buscador público. No se usa para reemplazar fechas/datos oficiales.
        if pending_specs and cfg.get('search_index_fallback', True):
            print('\n--- FACEBOOK: INDICE PUBLICO DE RESPALDO ---', flush=True)
            total_index = len(pending_specs)
            for idx, spec in enumerate(pending_specs, start=1):
                got, errs = _scrape_facebook_search_index(http, spec, int(cfg.get('max_index_posts_per_page', 6)), progress=f'[{idx}/{total_index}]')
                out.extend(got)
                errors.extend(errs)

    # Filtro final común para Graph, navegador e índice: evita que una fuente de respaldo
    # vuelva a introducir publicaciones antiguas. Si no conocemos la fecha, conservamos el item
    # y marcamos freshness_unknown para que la app pueda decidir.
    recent_hours = max(1, int(cfg.get('recent_hours', 72)))
    recent_out: list[Item] = []
    for item in out:
        age = _fb_age_hours(item.published_at)
        if age is not None and age > recent_hours:
            continue
        item.extra.setdefault('age_hours', age)
        item.extra.setdefault('freshness_unknown', item.published_at is None)
        recent_out.append(item)
    out = recent_out

    if not token and mode == 'graph':
        errors.append('Facebook Graph omitido: falta META_ACCESS_TOKEN.')
    if not out and mode in {'auto', 'public', 'both', 'browser'}:
        errors.append('Facebook: no se obtuvieron posts visibles. Revisa los errores por página en manifest.json.')
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
ASSIST_HINTS = ("asistencia", "asistencias", "asistente", "asistentes", "assist")
OWN_GOAL_HINTS = ("autogol", "autogoles", "own goal", "own goals")


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


def _fix_standings_dg(rows: list[list[str]]) -> list[list[str]]:
    # Algunas fuentes (ej. fbf.com.bo) publican la columna DG (diferencia de
    # gol) con un dígito de más por error propio de su sitio (ej. "+111" en
    # vez de "+11"). En vez de confiar en ese texto, la recalculamos como
    # GF - GC cuando ambas columnas existen, así el dato siempre es correcto
    # aunque la fuente tenga un typo.
    header = rows[0]
    norm = [clean_text(h).lower() for h in header]
    try:
        gf_idx = norm.index("gf")
        gc_idx = norm.index("gc")
        dg_idx = next(i for i, h in enumerate(norm) if h in ("dg", "dif", "diff"))
    except (ValueError, StopIteration):
        return rows
    fixed = [header]
    for row in rows[1:]:
        if len(row) <= max(gf_idx, gc_idx, dg_idx):
            fixed.append(row)
            continue
        try:
            gf = int(re.sub(r"[^\d-]", "", row[gf_idx]) or 0)
            gc = int(re.sub(r"[^\d-]", "", row[gc_idx]) or 0)
        except ValueError:
            fixed.append(row)
            continue
        diff = gf - gc
        new_row = list(row)
        new_row[dg_idx] = f"+{diff}" if diff > 0 else str(diff)
        fixed.append(new_row)
    return fixed


def _row_logo(tr: Tag, base_url: str) -> str:
    # El escudo del equipo vive en la celda del nombre (ej. FBF: td.data-name
    # con un <img data-src="..."> lazy-loaded). Tomamos la primera imagen
    # "de verdad" de la fila, ignorando placeholders base64 en blanco.
    for img in tr.find_all("img"):
        src = img.get("data-src") or img.get("data-lazyloaded-src") or img.get("src") or ""
        if src and not src.startswith("data:"):
            return absolute_url(base_url, str(src))
    return ""


# Mapa global equipo(normalizado) -> URL de escudo, juntado de CUALQUIER
# fuente que tenga imágenes reales en sus tablas (ej. FBF). Wikipedia (la
# fuente principal de tablas ahora) no publica escudos en "Clasificación",
# así que sin esto la tabla de posiciones queda sin ningún logo aunque sí
# existan en otro lado.
TEAM_LOGOS: dict[str, str] = {}


def _harvest_team_logos(soup: BeautifulSoup, base_url: str) -> None:
    for table in soup.find_all("table"):
        for tr in table.find_all("tr"):
            logo = _row_logo(tr, base_url)
            if not logo:
                continue
            for cell in tr.find_all(["th", "td"]):
                text = clean_text(cell.get_text(" ", strip=True))
                # Nombre de equipo real: texto de varias letras, no un
                # número/posición/porcentaje ("1", "+8", "34", "0.73").
                if len(text) >= 3 and re.search(r"[a-zA-ZÀ-ÿ]{3,}", text):
                    key = normalize_title(text)
                    if key and key not in TEAM_LOGOS:
                        TEAM_LOGOS[key] = logo
                    break
            else:
                continue


def _backfill_logos(table_dict: dict[str, Any]) -> None:
    extra = table_dict.get("extra") if isinstance(table_dict.get("extra"), dict) else None
    if not extra:
        return
    rows = extra.get("rows") or []
    if len(rows) < 2:
        return
    header_norm = [clean_text(h).lower() for h in rows[0]]
    try:
        name_idx = header_norm.index("equipo")
    except ValueError:
        return
    if any(extra.get("logos") or []):
        return  # ya trae escudos propios (ej. tabla de FBF); no pisar.
    logos = [""]  # fila 0 = header, sin logo
    for row in rows[1:]:
        name = row[name_idx] if name_idx < len(row) else ""
        logos.append(TEAM_LOGOS.get(normalize_title(name), ""))
    extra["logos"] = logos


def _table_row_cells(tr: Tag, pending: dict[int, list]) -> list[str]:
    # Maneja rowspan (ej. Wikipedia: la columna "Fecha" solo aparece una vez
    # por día y "cubre" varios partidos). Sin esto, las columnas de las filas
    # siguientes se corren una posición a la izquierda y terminan mezcladas
    # (la Hora queda donde debería ir la Fecha, etc.).
    row: dict[int, str] = {}
    for col in list(pending.keys()):
        text, remaining = pending[col]
        row[col] = text
        remaining -= 1
        if remaining <= 0:
            del pending[col]
        else:
            pending[col] = [text, remaining]
    col = 0
    for cell in tr.find_all(["th", "td"]):
        while col in row:
            col += 1
        text = clean_text(cell.get_text(" ", strip=True))
        try:
            colspan = int(cell.get("colspan", 1) or 1)
        except ValueError:
            colspan = 1
        try:
            rowspan = int(cell.get("rowspan", 1) or 1)
        except ValueError:
            rowspan = 1
        for i in range(colspan):
            row[col + i] = text
            if rowspan > 1:
                pending[col + i] = [text, rowspan - 1]
        col += colspan
    if not row:
        return []
    return [row.get(i, "") for i in range(max(row.keys()) + 1)]


def extract_tables(soup: BeautifulSoup, source: dict[str, Any], base_url: str) -> list[Item]:
    out: list[Item] = []
    for idx, table in enumerate(soup.find_all("table")):
        rows = []
        logos = []
        pending: dict[int, list] = {}
        for tr in table.find_all("tr"):
            cells = _table_row_cells(tr, pending)
            if cells and any(cells):
                rows.append(cells)
                logos.append(_row_logo(tr, base_url))
        if len(rows) < 2:
            continue
        heading = _heading_before(table)
        probe = (heading + " " + " ".join(rows[0])).lower()
        # Algunas fuentes (ej. Wikipedia) meten una fila-título de una sola
        # celda ("Fecha 1") antes de la fila real de encabezados; con colspan
        # expandido esa celda se repite en varias columnas (mismo texto
        # repetido), no queda en 1 sola celda. Si pasa eso, la clasificación
        # debe mirar la segunda fila, no la fila-título.
        is_caption_row = len(set(rows[0])) <= 1
        header_row = rows[1] if is_caption_row and len(rows) > 1 else rows[0]
        header_norm = [clean_text(h).lower() for h in header_row]
        # Quita puntos/espacios ("Pts." -> "pts") para no perder la señal
        # fuerte solo porque una fuente (ej. Wikipedia) le pone punto a la
        # abreviatura.
        header_stripped = [re.sub(r"[^a-z]", "", h) for h in header_norm]
        is_assists = any(x in probe for x in ASSIST_HINTS)
        kind = "table"
        # Torneos de grupos (Libertadores, Sudamericana) publican tablas
        # comparativas cruzadas ("Tabla de segundos/terceros": comparan los
        # 2.os o 3.os de cada grupo entre sí para definir clasificados) que
        # también tienen columnas PJ/Pts pero NO son la tabla de posiciones
        # de ningún grupo — se descartan explícitamente para que no le ganen
        # a la tabla real de un grupo (ej. "Grupo A") a la hora de elegir.
        is_cross_group_table = bool(re.search(r"tabla de (primeros|segundos|terceros|cuartos)", heading.lower()))
        strong_standings = (
            not is_cross_group_table
            and "pj" in header_stripped
            and any(p in header_stripped for p in ("pts", "puntos"))
        )
        # Igual que standings: exigir columnas Local+Visitante evita que una
        # tabla de curiosidades (ej. "goles en el mismo partido", tripletes)
        # se cuele como partido real solo por mencionar la palabra "partido".
        # Además exige que "Local" sea la PRIMERA columna: tablas como
        # "Autogoles" también tienen Local/Visitante (para decir en qué
        # partido pasó) pero empiezan con "N.º", no con el equipo local.
        strong_matches = (
            bool(header_stripped) and header_stripped[0] == "local"
            and "visitante" in header_stripped
        )
        # Señal fuerte y confiable primero: si las columnas son PJ + Pts, es
        # una tabla de posiciones sí o sí, sin depender de que el heading de
        # la página diga literalmente "tabla de posiciones" (algunas fuentes
        # solo ponen el nombre del torneo ahí). Evita además que "Tabla de
        # asistencias" se confunda con posiciones o goleadores solo por
        # compartir la palabra "tabla"/"goleador".
        if strong_standings:
            kind = "standings"
        elif is_assists:
            kind = "assists"
        elif any(x in probe for x in SCORER_HINTS):
            kind = "top_scorers"
        elif any(x in probe for x in OWN_GOAL_HINTS):
            kind = "own_goals"
        elif strong_matches:
            kind = "matches"
        elif any(x in probe for x in MATCH_HINTS):
            # Señal débil (solo por palabra clave, sin columnas Local/
            # Visitante): puede ser una tabla de curiosidades ("goles en el
            # mismo partido", tripletes, etc.), no un fixture real. La
            # dejamos como "table" genérica en vez de "matches" para no
            # ensuciar el merge de partidos.
            kind = "table"
        elif not is_assists and any(x in probe for x in TABLE_HINTS):
            kind = "standings"
        if kind == "standings":
            rows = _fix_standings_dg(rows)
        title = heading or f"Tabla {idx + 1}"
        if kind == "matches" and is_caption_row and rows[0][0]:
            # Sin esto, todas las tablas de "Fecha N" de la misma subsección
            # (ej. "Primera vuelta") comparten título y dedupe() las
            # colapsa en una sola, perdiendo 29 de 30 fechas del torneo.
            title = f"{title} — {clean_text(rows[0][0])}" if title else clean_text(rows[0][0])
        out.append(Item(
            id=stable_id(source["id"], kind, title, str(idx)), kind=kind, title=title, url=base_url,
            published_at=None, scraped_at=utc_now_iso(), source_id=source["id"], source_name=source["name"],
            source_type=source.get("source_type", "web"), source_authority=float(source.get("authority", 0.7)),
            scope=source.get("scope", "general"), competition=source.get("competition", "general"),
            # strong_standings: viene de columnas PJ+Pts reales, no de adivinar
            # por el título de la sección. build_current_tables la prioriza
            # por sobre otras tablas "standings" detectadas solo por heading
            # (ej. "Evolución de la clasificación" también contiene la
            # palabra "clasificación" pero no es la tabla de puntos).
            extra={"rows": rows, "logos": logos, "strong_standings": strong_standings},
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


_FECHA_LINE_RE = re.compile(r"^Fecha\s+\d+$", re.I)
_DATE_LINE_RE = re.compile(
    r"^(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)\s+\d{1,2}\s+de\s+\w+", re.I
)
_TIME_SCORE_RE = re.compile(
    r"^(?P<hh>\d{1,2}):(?P<mm>\d{2})\s+(?P<home>.+?)\s+(?P<hg>\d+)\s*[-–]\s*(?P<ag>\d+)\s+(?P<away>.+)$"
)
_TIME_VS_RE = re.compile(
    r"^(?P<hh>\d{1,2}):(?P<mm>\d{2})\s+(?P<home>.+?)\s+vs\.?\s+(?P<away>.+)$", re.I
)


def extract_prose_matches(soup: BeautifulSoup, source: dict[str, Any], base_url: str) -> list[Item]:
    # Fuentes como FutbolDeBolivia.net publican los resultados como texto
    # suelto ("18:00 Guabira 2 - 1 FC Universitario"), no en una <table> — su
    # tabla de posiciones real la arma JavaScript, así que no sirve de nada
    # buscar <table> ahí. En cambio el texto del resultado SÍ es HTML
    # estático y se puede parsear línea por línea.
    container = soup.find(class_=re.compile("post-body|entry-content")) or soup
    text = container.get_text("\n", strip=True)
    lines = [clean_text(l) for l in text.split("\n") if clean_text(l)]

    by_fecha: dict[str, list[list[str]]] = defaultdict(list)
    current_fecha = "Fecha 1"
    current_date = ""
    for line in lines:
        if _FECHA_LINE_RE.match(line):
            current_fecha = line
            continue
        if _DATE_LINE_RE.match(line):
            current_date = line
            continue
        m = _TIME_SCORE_RE.match(line)
        if m:
            by_fecha[current_fecha].append([
                m.group("home").strip(), f"{m.group('hg')} – {m.group('ag')}", m.group("away").strip(),
                "", current_date, f"{m.group('hh')}:{m.group('mm')}",
            ])
            continue
        m = _TIME_VS_RE.match(line)
        if m:
            by_fecha[current_fecha].append([
                m.group("home").strip(), "–", m.group("away").strip(),
                "", current_date, f"{m.group('hh')}:{m.group('mm')}",
            ])

    if not by_fecha:
        return []
    heading_node = soup.find("h1") or soup.find("title")
    title_base = clean_text(heading_node.get_text(" ", strip=True))[:120] if heading_node else ""
    out: list[Item] = []
    for idx, (fecha, rows) in enumerate(by_fecha.items()):
        out.append(Item(
            id=stable_id(source["id"], "matches_prose", fecha, str(idx)), kind="matches",
            title=f"{title_base} — {fecha}" if title_base else fecha, url=base_url,
            published_at=None, scraped_at=utc_now_iso(), source_id=source["id"], source_name=source["name"],
            source_type=source.get("source_type", "web"), source_authority=float(source.get("authority", 0.7)),
            scope=source.get("scope", "general"), competition=source.get("competition", "general"),
            extra={"rows": [[fecha], ["Local", "Resultado", "Visitante", "Estadio", "FechaPartido", "Hora"], *rows]},
        ))
    return out


def extract_footballbox_matches(soup: BeautifulSoup, source: dict[str, Any], base_url: str) -> list[Item]:
    # Copa Libertadores/Sudamericana (fases eliminatorias: llaves, octavos,
    # etc.) no publican una tabla grande "Fecha N" como la liga local — cada
    # partido es su PROPIA tablita de 2 filas (marcador + goleadores),
    # plantilla "footballbox" de Wikipedia (class="vevent"). Hay que juntar
    # todas esas tablitas sueltas por ronda para poder reusar el mismo merge
    # de partidos que ya usamos para las fechas de la liga.
    boxes = [t for t in soup.find_all("table") if "vevent" in (t.get("class") or [])]
    if not boxes:
        return []
    by_round: dict[str, list[list[str]]] = defaultdict(list)
    for table in boxes:
        pending: dict[int, list] = {}
        rows = []
        for tr in table.find_all("tr"):
            cells = _table_row_cells(tr, pending)
            if cells and any(cells):
                rows.append(cells)
        if not rows or len(rows[0]) < 4:
            continue
        date_time, home, score, away = rows[0][0], rows[0][1], rows[0][2], rows[0][3]
        stadium = rows[0][4] if len(rows[0]) > 4 else ""
        round_name = _heading_before(table) or "Fase final"
        by_round[round_name].append([
            clean_text(home), clean_text(score), clean_text(away), clean_text(stadium), clean_text(date_time),
        ])
    out: list[Item] = []
    for idx, (round_name, matches) in enumerate(by_round.items()):
        out.append(Item(
            id=stable_id(source["id"], "footballbox", round_name, str(idx)), kind="matches",
            title=round_name, url=base_url, published_at=None, scraped_at=utc_now_iso(),
            source_id=source["id"], source_name=source["name"], source_type=source.get("source_type", "web"),
            source_authority=float(source.get("authority", 0.7)), scope=source.get("scope", "general"),
            competition=source.get("competition", "general"),
            extra={"rows": [[round_name], ["Local", "Resultado", "Visitante", "Estadio", "FechaPartido"], *matches]},
        ))
    return out


def scrape_web_source(http, source: dict[str, Any]) -> list[Item]:
    r = http.get(source["url"])
    soup = BeautifulSoup(r.content, "lxml")
    # Aparte de si se confía en las stats de esta fuente (skip_tables), sus
    # escudos sirven igual para "vestir" la tabla de Wikipedia que no trae
    # imágenes.
    _harvest_team_logos(soup, r.url)
    items = []
    items.extend(extract_jsonld(soup, source, r.url))
    items.extend(extract_news_cards(soup, source, r.url))
    # Algunas fuentes tienen la tabla incrustada desactualizada (ej. el sitio
    # de la FBF quedó pegado en una fecha vieja del torneo); skip_tables deja
    # scrapear sus noticias igual, pero no usa su tabla de posiciones/goleadores.
    if not source.get("skip_tables", False):
        items.extend(extract_tables(soup, source, r.url))
        items.extend(extract_scorer_text(soup, source, r.url))
    if source.get("prose_matches", False):
        items.extend(extract_prose_matches(soup, source, r.url))
    if source.get("footballbox_matches", False):
        items.extend(extract_footballbox_matches(soup, source, r.url))
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
        "assists": _serialize(by_kind.get("assists", [])),
        "own_goals": _serialize(by_kind.get("own_goals", [])),
        "matches": _serialize(by_kind.get("matches", [])),
        "tables": _serialize(by_kind.get("table", [])),
        "competitions": {k: _serialize(sorted(v, key=lambda z: (z.rank_score, z.published_at or ""), reverse=True)) for k, v in by_comp.items()},
    }


def _structured_quality(item: Item) -> float:
    rows = item.extra.get('rows') if isinstance(item.extra, dict) else None
    nrows = len(rows) if isinstance(rows, list) else 0
    official_bonus = 0.12 if item.source_type in {'federation', 'confederation'} else 0.0
    kind_bonus = 0.08 if item.kind == 'standings' else 0.03 if item.kind in {'matches','top_scorers','assists','own_goals'} else 0.0
    row_bonus = min(0.08, nrows / 250.0)
    return round(float(item.source_authority) + official_bonus + kind_bonus + row_bonus, 4)


def _jornada_num(label: str) -> int:
    m = re.search(r"\d+", label or "")
    return int(m.group(0)) if m else 999


def _merge_matches(match_items: list[Item]) -> dict[str, Any]:
    # A diferencia de standings/top_scorers (una sola tabla vigente), los
    # partidos pueden venir repartidos entre varias fuentes que NO se
    # solapan (ej. FutbolDeBolivia publica Grupo A/B/C/D en 4 páginas
    # distintas). Elegir "la mejor fuente" y descartar el resto perdería 3
    # de los 4 grupos. En cambio se combina por PARTIDO (fecha + equipos):
    # si dos fuentes traen el mismo partido, gana la de mejor puntaje; si
    # son partidos distintos (otro grupo), se quedan ambos.
    best_by_match: dict[tuple[str, str, str], tuple[float, list[str], str]] = {}
    for it in sorted(match_items, key=_structured_quality, reverse=True):
        rows = it.extra.get("rows") if isinstance(it.extra, dict) else None
        if not rows or len(rows) < 3:
            continue
        jornada = clean_text(rows[0][0]) if rows[0] else ""
        quality = _structured_quality(it)
        for row in rows[2:]:
            if not row or len(row) < 3:
                continue
            key = (normalize_title(jornada), normalize_title(row[0]), normalize_title(row[2]))
            if key not in best_by_match or quality > best_by_match[key][0]:
                best_by_match[key] = (quality, [jornada, *row], it.source_name)

    merged_rows = [v[1] for v in best_by_match.values()]
    merged_rows.sort(key=lambda r: _jornada_num(r[0]))
    sources_used = sorted({v[2] for v in best_by_match.values()})

    return {
        "kind": "matches",
        "title": "Partidos por fecha",
        "source_id": "merged",
        "source_name": " + ".join(sources_used),
        "scope": match_items[0].scope if match_items else "",
        "competition": match_items[0].competition if match_items else "",
        "scraped_at": max((it.scraped_at or "" for it in match_items), default=""),
        "extra": {
            "header": ["Fecha", "Local", "Resultado", "Visitante", "Estadio", "FechaPartido", "Hora"],
            "rows": merged_rows,
            "selected_as_current": True,
            "selection_reason": "se combina por partido (fecha+equipos) entre todas las fuentes, sin duplicar",
        },
    }


def _compute_standings_from_matches(matches_table: dict[str, Any]) -> dict[str, Any] | None:
    # Cuando ninguna fuente trae una tabla de posiciones lista (ej. Copa
    # Paceña: 365Scores/FutbolDeBolivia arman la suya con JavaScript), se
    # calcula la nuestra sumando resultado por resultado: 3 pts victoria,
    # 1 empate, 0 derrota. Solo cuenta partidos que ya tienen marcador
    # (rows con "Resultado" tipo "N – N"; los pendientes traen "–" solo).
    rows = matches_table.get("extra", {}).get("rows", [])
    score_re = re.compile(r"^(\d+)\s*[-–]\s*(\d+)$")
    stats: dict[str, dict[str, int]] = {}

    def team(name: str) -> dict[str, int]:
        return stats.setdefault(name, {"pj": 0, "g": 0, "e": 0, "p": 0, "gf": 0, "gc": 0})

    for row in rows:
        # El merge antepone la fecha: [Fecha, Local, Resultado, Visitante, ...]
        if len(row) < 4:
            continue
        home, resultado, away = row[1], row[2], row[3]
        m = score_re.match(clean_text(resultado))
        if not m or not home or not away:
            continue
        hg, ag = int(m.group(1)), int(m.group(2))
        h, a = team(home), team(away)
        h["pj"] += 1; a["pj"] += 1
        h["gf"] += hg; h["gc"] += ag
        a["gf"] += ag; a["gc"] += hg
        if hg > ag:
            h["g"] += 1; a["p"] += 1
        elif hg < ag:
            a["g"] += 1; h["p"] += 1
        else:
            h["e"] += 1; a["e"] += 1

    if not stats:
        return None
    table_rows = []
    for name, s in stats.items():
        pts = s["g"] * 3 + s["e"]
        dg = s["gf"] - s["gc"]
        table_rows.append((pts, dg, s["gf"], name, s))
    table_rows.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)

    header = ["Pos", "Equipo", "Pts", "PJ", "G", "E", "P", "GF", "GC", "DG"]
    out_rows = [header]
    for pos, (pts, dg, gf, name, s) in enumerate(table_rows, start=1):
        out_rows.append([str(pos), name, str(pts), str(s["pj"]), str(s["g"]), str(s["e"]), str(s["p"]),
                          str(s["gf"]), str(s["gc"]), (f"+{dg}" if dg > 0 else str(dg))])

    return {
        "kind": "standings",
        "title": "Tabla calculada a partir de resultados",
        "source_id": "computed",
        "source_name": f"Calculada desde: {matches_table.get('source_name', '')}",
        "scope": matches_table.get("scope", ""),
        "competition": matches_table.get("competition", ""),
        "scraped_at": matches_table.get("scraped_at", ""),
        "extra": {
            "rows": out_rows,
            "selected_as_current": True,
            "selection_reason": "ninguna fuente trae tabla de posiciones lista; se calculó sumando los resultados de matches",
        },
    }


def _merge_group_standings(items: list[Item]) -> dict[str, Any]:
    # Torneos por grupos (Libertadores: Grupo A..H) tienen una tabla de
    # posiciones POR GRUPO, no una sola del torneo entero. Antes se elegía
    # solo "la mejor" (ganaba 1 de 8 grupos, se perdían los otros 7). Ahora
    # se junta un grupo por título (ej. "Grupo A"), quedándose con la mejor
    # versión de CADA grupo si hay más de una fuente, y se concatenan todas
    # con una columna "Grupo" al frente para no perder el contexto.
    #
    # OJO: el merge se hace SOLO entre tablas de la MISMA fuente (misma
    # página). Si se juntaran tablas de fuentes distintas por título, una
    # tabla completa de un sitio (ej. "Primera División 2026") y la tabla
    # completa de otro sitio (ej. "Clasificación") se tratarían como si
    # fueran "dos grupos" del mismo torneo, duplicando todos los equipos.
    by_source: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        by_source[it.source_id].append(it)
    best_source_id = max(by_source, key=lambda sid: max(_structured_quality(x) for x in by_source[sid]))
    items = by_source[best_source_id]

    best_by_group: dict[str, tuple[float, Item]] = {}
    for it in items:
        label = clean_text(it.title) or "General"
        key = normalize_title(label)
        quality = _structured_quality(it)
        if key not in best_by_group or quality > best_by_group[key][0]:
            best_by_group[key] = (quality, it)
    groups = sorted(best_by_group.values(), key=lambda t: t[1].title)

    if len(groups) <= 1:
        it = groups[0][1] if groups else items[0]
        d = it.to_dict()
        d.setdefault('extra', {})['selection_score'] = _structured_quality(it)
        d['extra']['selected_as_current'] = True
        d['extra']['selection_reason'] = 'única tabla de posiciones detectada para esta competición'
        return d

    base_rows = groups[0][1].extra.get('rows', []) if isinstance(groups[0][1].extra, dict) else []
    header = base_rows[0] if base_rows else []
    merged_rows = [["Grupo", *header]]
    for _, it in groups:
        rows = it.extra.get('rows', []) if isinstance(it.extra, dict) else []
        for row in rows[1:]:
            merged_rows.append([it.title, *row])

    return {
        "kind": "standings",
        "title": "Tabla por grupos",
        "source_id": "merged",
        "source_name": " + ".join(sorted({it.title for _, it in groups})),
        "scope": groups[0][1].scope,
        "competition": groups[0][1].competition,
        "scraped_at": max((it.scraped_at or "" for it in items), default=""),
        "extra": {
            "rows": merged_rows,
            "selected_as_current": True,
            "selection_reason": f"se combinaron {len(groups)} grupos detectados en vez de mostrar uno solo",
        },
    }


def build_current_tables(items: list[Item]) -> dict[str, Any]:
    """Elige una sola tabla vigente por competición/tipo para que la app no tenga que adivinar."""
    candidates = [
        x for x in items
        if x.scope in {'bolivia', 'conmebol'}
        and x.kind in {'standings', 'table', 'matches', 'top_scorers', 'assists', 'own_goals'}
    ]
    grouped: dict[str, dict[str, list[Item]]] = defaultdict(lambda: defaultdict(list))
    for x in candidates:
        logical_kind = 'standings' if x.kind in {'standings','table'} else x.kind
        grouped[x.competition][logical_kind].append(x)
    competitions: dict[str, Any] = {}
    for comp, kinds in grouped.items():
        chosen: dict[str, Any] = {}
        # "matches" primero: si no hay standings real, se calcula desde acá.
        if "matches" in kinds:
            chosen["matches"] = _merge_matches(kinds["matches"])
        for kind, rows in kinds.items():
            if kind == "matches":
                continue
            if kind == "standings":
                strong = [z for z in rows if isinstance(z.extra, dict) and z.extra.get("strong_standings")]
                chosen["standings"] = _merge_group_standings(strong if strong else rows)
                continue
            rows = sorted(rows, key=lambda z: (_structured_quality(z), z.scraped_at or ''), reverse=True)
            if rows:
                d = rows[0].to_dict()
                d.setdefault('extra', {})['selection_score'] = _structured_quality(rows[0])
                d['extra']['selected_as_current'] = True
                d['extra']['selection_reason'] = 'prioriza fuente oficial/autoridad + tipo de tabla + cantidad de filas'
                chosen[kind] = d
        if "standings" not in chosen and "matches" in chosen:
            computed = _compute_standings_from_matches(chosen["matches"])
            if computed:
                chosen["standings"] = computed
        if "standings" in chosen:
            _backfill_logos(chosen["standings"])
        if chosen:
            competitions[comp] = chosen
    return {
        'schema_version': 4,
        'generated_at': utc_now_iso(),
        'policy': 'una tabla por competición/tipo; fuentes oficiales tienen prioridad',
        'competitions': competitions,
    }


def build_app_feed(items: list[Item], limit: int = 250) -> dict[str, Any]:
    feed = [x for x in items if x.kind in {'news','social','video'}]
    feed.sort(key=lambda z: (z.rank_score, z.published_at or ''), reverse=True)
    return {
        'schema_version': 4,
        'generated_at': utc_now_iso(),
        'items': [x.to_dict() for x in feed[:limit]],
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
    source_status.append({"id": "facebook", "name": "Facebook (Graph/public web)", "ok": len(fb) > 0, "items": len(fb)})
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

    facebook_items = [x for x in live if x.source_type in {"facebook", "facebook_browser_public", "facebook_search_index", "facebook_public_http"}]
    facebook_items.sort(key=lambda z: (z.published_at or "", z.rank_score), reverse=True)
    buckets["facebook_latest.json"] = {
        "schema_version": 4,
        "generated_at": utc_now_iso(),
        "items": _serialize(facebook_items[:200]),
    }
    buckets["app_feed.json"] = build_app_feed(live, 250)
    buckets["current_tables.json"] = build_current_tables(live)

    for name, payload in buckets.items():
        json_dump(output_dir / name, payload)

    manifest = {
        "schema_version": 4,
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
