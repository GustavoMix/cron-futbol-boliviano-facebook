import re
import requests
from bs4 import BeautifulSoup

UA = "FutbolBoliviaAggregator/1.0 (+contacto-del-desarrollador)"

PAGES = [
    "https://fbf.com.bo/torneos/division-profesional/",
    "https://fbf.com.bo/torneos/copa-pacena/",
    "https://fbf.com.bo/sport-team/always-ready/",
]

KEYWORDS = [
    "partido", "partidos", "fixture", "resultado", "resultados", "calendario",
    "próxim", "proxim", "jornada", "vs", "fecha",
    "tarjeta", "amarilla", "roja", "sancion", "sanción", "expulsa", "acumula",
]


def report_tables(soup):
    tables = soup.find_all("table")
    print(f"  <table> encontradas: {len(tables)}")
    for i, t in enumerate(tables):
        heading = t.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
        heading_text = heading.get_text(" ", strip=True) if heading else "(sin heading)"
        first_row = t.find("tr")
        first_row_text = first_row.get_text(" | ", strip=True) if first_row else ""
        print(f"    [{i}] heading='{heading_text}' primera_fila='{first_row_text[:150]}'")


def report_keyword_hits(soup):
    text = soup.get_text(" ", strip=True)
    lower = text.lower()
    for kw in KEYWORDS:
        idxs = [m.start() for m in re.finditer(re.escape(kw), lower)][:3]
        if not idxs:
            continue
        print(f"  keyword '{kw}': {len(re.findall(re.escape(kw), lower))} apariciones. Ejemplos:")
        for idx in idxs:
            snippet = text[max(0, idx - 60): idx + 80].replace("\n", " ")
            print(f"      ...{snippet}...")


def report_iframes_scripts(soup):
    iframes = soup.find_all("iframe")
    print(f"  <iframe>: {len(iframes)}")
    for f in iframes[:5]:
        print(f"    src={f.get('src')}")
    scripts = soup.find_all("script", src=True)
    interesting = [s for s in scripts if any(x in (s.get("src") or "").lower() for x in ["api", "fixture", "widget", "match", "livescore", "ajax"])]
    print(f"  <script src> sospechosos (api/fixture/widget/match/livescore/ajax): {len(interesting)}")
    for s in interesting[:10]:
        print(f"    {s.get('src')}")
    # Buscar endpoints /wp-json/ típicos de WordPress
    body = str(soup)
    wpjson = sorted(set(re.findall(r"[\"'](/wp-json/[^\"']+)[\"']", body)))[:15]
    if wpjson:
        print(f"  Endpoints /wp-json/ detectados en el HTML:")
        for w in wpjson:
            print(f"    {w}")


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "es-BO,es;q=0.9"})
    for url in PAGES:
        print("=" * 100)
        print("URL:", url)
        try:
            r = session.get(url, timeout=25)
            r.raise_for_status()
        except Exception as exc:
            print("  ERROR al descargar:", exc)
            continue
        soup = BeautifulSoup(r.text, "lxml")
        print(f"  status={r.status_code} bytes={len(r.text)}")
        report_tables(soup)
        report_keyword_hits(soup)
        report_iframes_scripts(soup)
        print()


if __name__ == "__main__":
    main()
