from __future__ import annotations
import json
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path('.')
PART = ROOT / 'partials'


def now_iso():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def load(path, default):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:
        return default


def ts(s):
    try:
        return datetime.fromisoformat((s or '').replace('Z', '+00:00')).timestamp()
    except Exception:
        return 0


def norm(s):
    return re.sub(r'\s+', ' ', (s or '')).strip()


def clean_social_text(text: str, page_name: str = '') -> str:
    """Quita nombre de página, tiempo relativo, reacciones, comentarios y UI de Facebook."""
    t = norm(text)
    if page_name and t.lower().startswith(page_name.lower()):
        t = norm(t[len(page_name):])
    # Si el nombre visible de la página difiere del configurado (ej.
    # "Club Deportivo Oriente Petrolero" vs "Oriente Petrolero"), corta
    # todo lo que precede al tiempo relativo.
    t = re.sub(r'^.{2,90}?\s+(?:\d+\s*(?:min|h|hora|horas|d|día|dias|días))\s*[·•-]\s*', '', t, flags=re.I)
    t = re.sub(r'^(?:hace\s+)?\d+\s*(?:min|h|hora|horas|d|día|dias|días)\s*[·•-]?\s*', '', t, flags=re.I)
    t = re.sub(r'^(?:ahora|hace un momento)\s*[·•-]?\s*', '', t, flags=re.I)
    for marker in ('Todas las reacciones:', 'All reactions:', 'Me gusta Comentar', 'Like Comment', 'Ver más comentarios'):
        pos = t.lower().find(marker.lower())
        if pos >= 0:
            t = t[:pos]
    t = re.sub(r'\s*…?\s*Ver más\b', ' ', t, flags=re.I)
    t = re.sub(r'\bYOUTUBE\.COM\b', ' ', t, flags=re.I)
    t = re.sub(r'\b\d{1,2}:\d{2}\s*/\s*\d{1,2}:\d{2}\b', ' ', t)
    t = re.sub(r'\s+\+\d+\s*$', '', t)
    return norm(t).strip(' ·-|—')


def clean_web_text(text: str, title: str = '') -> str:
    t = norm(text)
    title = norm(title)
    if title and t.lower().startswith(title.lower()):
        t = norm(t[len(title):])
    # Fecha de tarjeta repetida al comienzo.
    t = re.sub(r'^\s*\d{1,2}[/-]\d{1,2}[/-]\d{4}\s*[-–—·|:]?\s*', '', t)
    t = re.sub(r'\b(?:Tweet|Post)\s*#?\w*\b', ' ', t, flags=re.I)
    t = re.sub(r'\s*…?\s*Ver más\b', ' ', t, flags=re.I)
    t = re.sub(r'\bLeer(?:\s+m[aá]s?)?\s*$', ' ', t, flags=re.I)
    return norm(t)


def social_is_editorial(item: dict) -> bool:
    text = norm(f"{item.get('title','')} {item.get('text','')}").lower()
    if not text:
        return False
    negative = (
        'buenos dias', 'buenos días', 'vamos por la victoria', 'no dejemos de alentar',
        'todos a villa ingenio', 'todo por nuestros colores', 'vestuario guarda la calma',
        'outlet', 'tienda', 'camiseta', 'abrígate', 'abrigate', 'manto blanco',
        'inicia el partido', 'comienza el partido', 'comienzo el segundo tiempo',
        'gooooo', 'goooool', 'no somos la mitad', 'último día', 'ultimo dia',
    )
    if any(x in text for x in negative):
        return False
    content = norm(item.get('text') or '').lower()
    if content.startswith('final del partido') and len(content) < 100:
        return False
    positive = (
        'clasific', 'eliminación', 'eliminacion', 'resultado', 'resultados', 'final del partido',
        'fichaje', 'refuerzo', 'contrat', 'bienvenido', 'lesión', 'lesion', 'baja',
        'sanción', 'sancion', 'suspendido', 'suspensión', 'suspension', 'convocad',
        'titulares', 'alineación', 'alineacion', 'designación arbitral', 'designacion arbitral',
        'reprogram', 'octavos', 'cuartos', 'semifinal', 'copa sudamericana', 'copa libertadores',
        'sumó sus primeras', 'sumo sus primeras', 'goleadores', 'tabla de posiciones',
    )
    if any(x in text for x in positive):
        return True
    source = (item.get('source_name') or '').lower()
    # Medios deportivos: análisis/debate sí aporta contexto, aunque no sea un comunicado oficial.
    if any(x in source for x in ('tigo sports', 'futbolman', 'fútbolcanal', 'red uno', 'diez')):
        if any(x in text for x in ('análisis', 'analisis', 'debate', 'partido', 'liga', 'copa', 'gol')):
            return True
    return False

def short_title(text: str, limit: int = 150) -> str:
    t = norm(text)
    if len(t) <= limit:
        return t
    cut = t[:limit]
    for sep in ('. ', '! ', '? ', ' — '):
        idx = cut.rfind(sep)
        if idx >= 50:
            return cut[:idx + (1 if sep[0] in '.!?' else 0)].strip()
    return cut.rsplit(' ', 1)[0].strip() + '…'


def contextual_title(item: dict, title: str) -> str:
    """Hace entendibles títulos demasiado genéricos sin inventar contenido."""
    t = norm(title)
    low = t.lower()
    source = norm(str(item.get('source_name') or '')).replace('Facebook · ', '')
    comp = norm(str(item.get('competition') or '')).replace('_', ' ').title()
    generic = (
        low.startswith('designación arbitral') or low.startswith('designacion arbitral') or
        re.match(r'^resultados?\s*[–—|-]?\s*fecha\s*\d+', low) or
        low in {'resultados', 'tabla de posiciones', 'goleadores'}
    )
    if not generic:
        return t
    # Si ya nombra Copa/Liga/Fecha, el propio título trae contexto suficiente.
    if any(word in low for word in ('copa ', 'liga ', 'división ', 'division ')):
        return t
    context = source
    if context and context.lower() not in low:
        return short_title(f"{context} — {t}")
    return t



def infer_news_date(item: dict) -> tuple[str, str]:
    """Fecha sin abrir el artículo: URL del medio o tiempo relativo del card."""
    url = str(item.get('url') or '')
    sid = str(item.get('source_id') or '').lower()
    path = url.split('?', 1)[0].rstrip('/')
    if 'diez' in sid or 'diez.bo' in url.lower():
        dated = re.search(r'/(20\d{2})-(\d{1,2})-(\d{1,2})-(\d{1,2})-(\d{1,2})-(\d{1,2})(?:-|$)', path)
        if dated:
            try:
                y,mo,d,hh,mm,ss=map(int,dated.groups())
                return datetime(y,mo,d,hh,mm,ss,tzinfo=timezone(timedelta(hours=-4))).isoformat(), 'url_datetime'
            except Exception:
                pass
        m = re.search(r'_(\d{10})(?:$|\D)', path)
        if m:
            try:
                dt = datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc)
                if 2020 <= dt.year <= 2035:
                    return dt.isoformat().replace('+00:00', 'Z'), 'url_epoch'
            except Exception:
                pass
    if 'reduno' in sid or 'reduno.com.bo' in url.lower():
        m = re.search(r'(20\d{2}\d{7,10})$', path)
        if m:
            digits=m.group(1); year=int(digits[:4]); tail=digits[4:]; cands=[]
            for ml in (2,1):
                if len(tail)<=ml: continue
                month=int(tail[:ml])
                if not 1<=month<=12: continue
                rest=tail[ml:]
                for dl in (2,1):
                    if len(rest)<=dl: continue
                    day=int(rest[:dl]); clock=rest[dl:]
                    if not 1<=day<=31 or not 3<=len(clock)<=6: continue
                    for hl in (2,1):
                        if len(clock)<hl+2: continue
                        hour=int(clock[:hl]); minute=int(clock[hl:hl+2]); ss=clock[hl+2:]; second=int(ss) if ss else 0
                        if not (0<=hour<=23 and 0<=minute<=59 and 0<=second<=59): continue
                        try:cands.append(datetime(year,month,day,hour,minute,second,tzinfo=timezone(timedelta(hours=-4))))
                        except ValueError: pass
            if cands:
                now=datetime.now(timezone.utc); valid=[x for x in cands if x.astimezone(timezone.utc)<=now+timedelta(hours=6)] or cands
                return max(valid,key=lambda x:x.astimezone(timezone.utc)).isoformat(), 'url_datetime'
    probe=norm(f"{item.get('title','')} {item.get('text','')}")
    m=re.search(r'\bHace\s+(\d+)\s*(min(?:uto)?s?|h(?:ora)?s?|d[ií]as?)\b',probe,flags=re.I)
    if m:
        try: base=datetime.fromisoformat((item.get('scraped_at') or '').replace('Z','+00:00'))
        except Exception: base=datetime.now(timezone.utc)
        n=int(m.group(1)); unit=m.group(2).lower()
        delta=timedelta(minutes=n) if unit.startswith('min') else timedelta(hours=n) if unit.startswith('h') else timedelta(days=n)
        return (base-delta).astimezone(timezone.utc).isoformat().replace('+00:00','Z'), 'relative_card'
    return '', ''


def repair_news_date(item: dict) -> None:
    """Corrige fechas DD/MM/YYYY que versiones antiguas interpretaron como MM/DD."""
    if item.get('kind') != 'news':
        return
    probe = norm(f"{item.get('title','')} {item.get('text','')}")[:1200]
    m = re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b', probe)
    if not m:
        if not item.get('published_at'):
            inferred, source = infer_news_date(item)
            if inferred:
                item['published_at'] = inferred
                item.setdefault('extra', {})['date_source'] = source
        return
    d, mo, y = map(int, m.groups())
    if not (1 <= d <= 31 and 1 <= mo <= 12):
        return
    try:
        explicit = datetime(y, mo, d, 12, 0, tzinfo=timezone.utc)
    except ValueError:
        return
    current = item.get('published_at') or ''
    try:
        cur = datetime.fromisoformat(current.replace('Z', '+00:00'))
    except Exception:
        cur = None
    # Solo corrige si no hay fecha o si día/mes quedaron intercambiados.
    if cur is None or (cur.year == y and cur.month == d and cur.day == mo and d != mo):
        item['published_at'] = explicit.isoformat().replace('+00:00', 'Z')


def looks_like_stats_widget(item: dict) -> bool:
    probe = ' ' + norm(f"{item.get('title','')} {item.get('text','')}").lower() + ' '
    stat_tokens = sum(1 for token in (' pj ', ' pts ', ' gf ', ' gc ', ' dg ') if token in probe)
    if stat_tokens >= 3 or (' tabla de posiciones ' in probe and ' fecha ' in probe):
        return True
    title = norm(item.get('title') or '').lower()
    if re.search(r'\bgrupo\s+[a-h].*(resultados\s+y\s+posiciones|posiciones\s+y\s+resultados)', title):
        return True
    if 'resultados y posiciones' in title or 'posiciones y resultados' in title:
        return True
    return False

def content_quality(item: dict) -> float:
    extra = item.get('extra') if isinstance(item.get('extra'), dict) else {}
    existing = extra.get('content_quality')
    try:
        if existing is not None:
            return max(0.0, min(1.0, float(existing)))
    except Exception:
        pass
    text = norm(f"{item.get('title','')} {item.get('text','')}").lower()
    high = (
        'clasific', 'cuartos', 'octavos', 'semifinal', 'final', 'resultado', 'partido', 'fixture',
        'fecha', 'tabla', 'posición', 'posicion', 'goleador', 'lesión', 'lesion', 'baja', 'fichaje',
        'refuerzo', 'contrat', 'transfer', 'sanción', 'sancion', 'suspend', 'convocad', 'alineación',
        'alineacion', 'titular', 'gol', 'empate', 'victoria', 'derrota', 'reprogram', 'árbitro',
        'arbitro', 'designación', 'designacion', 'selección', 'seleccion', 'copa', 'liga',
    )
    low = (
        'buenos dias', 'buenos días', 'buen día', 'feliz cumple', 'tienda', 'camiseta', 'abrígate', 'abrigate',
        'merch', 'sponsor', 'patrocinador', 'panini', 'album panini', 'álbum panini', 'promo', 'promocion',
        'promoción', 'venta de entradas', 'entradas a la venta',
    )
    kind = item.get('kind')
    score = 0.50 if kind == 'news' else 0.35
    score += min(0.16, len(text) / 1800.0)
    if any(x in text for x in high):
        score += 0.30
    if any(x in text for x in low):
        score -= 0.72
    if re.search(r'\b(comienzo|inicia) (el )?(primer|segundo) tiempo\b', text):
        score -= 0.22
    if 'final de 45' in text:
        score -= 0.55
    return round(max(0.0, min(1.0, score)), 4)


def normalize_item(item: dict) -> dict:
    x = dict(item)
    repair_news_date(x)
    extra = dict(x.get('extra') or {})
    if str(x.get('source_type', '')).startswith('facebook') or x.get('platform') == 'facebook':
        page_name = extra.get('page_name') or str(x.get('source_name', '')).replace('Facebook · ', '')
        cleaned = clean_social_text(x.get('text') or x.get('title') or '', page_name)
        if cleaned:
            x['text'] = cleaned
            x['title'] = contextual_title(x, short_title(cleaned))
            extra['summary'] = cleaned[:360]
    else:
        text = clean_web_text(x.get('text') or '', x.get('title') or '')
        if text:
            x['text'] = text
            extra['summary'] = text[:360]
    q = content_quality({**x, 'extra': extra})
    extra['content_quality'] = q
    pub = x.get('published_at') or ''
    extra['published_date'] = pub[:10] if len(pub) >= 10 else ''
    x['published_date'] = extra['published_date']
    if len(pub) >= 10:
        try:
            d = datetime.fromisoformat(pub.replace('Z', '+00:00'))
            x['published_display'] = d.strftime('%d/%m/%Y')
        except Exception:
            x['published_display'] = pub[:10]
    else:
        x['published_display'] = ''
    x['extra'] = extra
    return x


def dedupe(items):
    d = {}
    for raw in items:
        x = normalize_item(raw)
        key = x.get('post_id') or x.get('url') or x.get('id')
        if not key:
            continue
        prev = d.get(key)
        if prev is None or ts(x.get('scraped_at')) >= ts(prev.get('scraped_at')):
            d[key] = x
    return list(d.values())


def editorial(items):
    out = []
    news_cutoff = datetime.now(timezone.utc) - timedelta(days=45)
    for x in items:
        if x.get('kind') == 'news':
            if looks_like_stats_widget(x):
                continue
            pub = x.get('published_at') or ''
            if not pub:
                continue
            try:
                if datetime.fromisoformat(pub.replace('Z', '+00:00')).astimezone(timezone.utc) < news_cutoff:
                    continue
            except Exception:
                continue
        if x.get('kind') in {'social', 'video'} and not social_is_editorial(x):
            continue
        q = content_quality(x)
        threshold = 0.27 if x.get('kind') == 'news' else 0.43
        if q < threshold:
            continue
        # Recalcula frescura porque los partials pueden venir de una corrida
        # anterior cuyo rank_score se calculó antes de reparar la fecha.
        try:
            pub_dt = datetime.fromisoformat((x.get('published_at') or '').replace('Z', '+00:00')).astimezone(timezone.utc)
            age_h = max(0.0, (datetime.now(timezone.utc) - pub_dt).total_seconds() / 3600.0)
            fresh = 0.5 ** (age_h / 30.0)
        except Exception:
            fresh = 0.0
        authority = max(0.0, min(1.0, float(x.get('source_authority') or 0.5)))
        score = 0.48 * fresh + 0.22 * authority + 0.30 * q
        x.setdefault('extra', {})['feed_freshness'] = round(fresh, 6)
        x['extra']['feed_score'] = round(score, 6)
        out.append(x)
    out.sort(key=lambda x: (float(x.get('extra', {}).get('feed_score') or 0), ts(x.get('published_at'))), reverse=True)
    return out


def write(name, obj):
    Path(name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    fb = []
    fb_meta = []
    for g in ('oficiales', 'clubes', 'medios'):
        p = PART / f'facebook_{g}.json'
        data = load(p, {})
        fb.extend(data.get('items', []))
        fb_meta.append({
            'group': g,
            'last_good_at': data.get('last_good_at'),
            'last_attempt_ok': data.get('last_attempt_ok'),
            'items': len(data.get('items', [])),
        })
    fb = dedupe(fb)
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    keep = []
    for x in fb:
        pub = x.get('published_at')
        if pub:
            try:
                if datetime.fromisoformat(pub.replace('Z', '+00:00')) < cutoff:
                    continue
            except Exception:
                pass
        keep.append(x)
    fb = keep
    fb.sort(key=lambda x: (ts(x.get('published_at')), float(x.get('rank_score') or 0)), reverse=True)

    generated = now_iso()
    facebook_latest = {'schema_version': 6, 'generated_at': generated, 'groups': fb_meta, 'items': fb[:300]}
    write('facebook_latest.json', facebook_latest)
    write('social.json', {'schema_version': 6, 'scope': 'social', 'generated_at': generated, 'items': fb[:300]})

    web_latest = dedupe(load(PART / 'web' / 'latest.json', {}).get('items', []))
    combined_latest = dedupe(web_latest + fb)
    combined_latest.sort(key=lambda x: (float(x.get('rank_score') or 0), ts(x.get('published_at'))), reverse=True)
    write('latest.json', {
        'schema_version': 6,
        'scope': 'latest',
        'generated_at': generated,
        'items': combined_latest[:300],
    })

    # Feed principal: usa el feed web ya depurado + solo Facebook relevante.
    web_feed = dedupe(load(PART / 'web' / 'app_feed.json', {}).get('items', []))
    combined_feed = editorial(dedupe(web_feed + fb))
    write('app_feed.json', {
        'schema_version': 6,
        'generated_at': generated,
        'policy': 'feed editorial: noticias deportivas coherentes; sin widgets de tablas, UI de Facebook ni promociones de bajo valor',
        'items': combined_feed[:300],
    })

    # Structured outputs stay sourced from web/official collector.
    for name in ('current_tables.json', 'bolivia.json', 'conmebol.json', 'internacional.json'):
        src = PART / 'web' / name
        if src.exists():
            Path(name).write_bytes(src.read_bytes())

    web_manifest = load(PART / 'web' / 'manifest.json', {})
    manifest = {
        'schema_version': 6,
        'generated_at': generated,
        'architecture': '3 Facebook groups + 1 web group; feed editorial + fases KO verificadas por serie completa',
        'facebook_groups': fb_meta,
        'totals': {
            'facebook_items': len(fb),
            'web_latest_items': len(web_latest),
            'app_feed_items': min(300, len(combined_feed)),
        },
        'web': {
            'generated_at': web_manifest.get('generated_at'),
            'totals': web_manifest.get('totals', {}),
            'errors': web_manifest.get('errors', []),
        },
        'notes': [
            'Facebook HTTP directo está desactivado.',
            'Si un grupo Facebook falla temporalmente, no se borra el último JSON bueno.',
            'app_feed elimina ruido de UI/comentarios/promociones de bajo valor.',
            'Libertadores/Sudamericana: un equipo aparece clasificado a cuartos solo después de completar la serie de octavos.',
            'Escudo real tiene prioridad; si no existe, se usa bandera del país como fallback.',
            'published_at conserva la fecha original; extra.published_date facilita mostrarla en el front.',
        ],
    }
    write('manifest.json', manifest)
    print(json.dumps(manifest['totals'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
