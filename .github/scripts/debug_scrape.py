import re
import requests
from bs4 import BeautifulSoup

UA = "FutbolBoliviaAggregator/1.0 (+contacto-del-desarrollador)"

CANDIDATE_URLS = [
    "https://fbf.com.bo/torneos/division-profesional/calendario/",
    "https://fbf.com.bo/torneos/division-profesional/resultados/",
    "https://fbf.com.bo/torneos/division-profesional/fixture/",
    "https://fbf.com.bo/calendario/",
    "https://fbf.com.bo/resultados/",
    "https://fbf.com.bo/partidos/",
    "https://fbf.com.bo/tarjetas/",
    "https://fbf.com.bo/sanciones/",
    "https://fbf.com.bo/disciplina/",
]


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "es-BO,es;q=0.9"})

    print("#" * 100)
    print("# 1) Probar URLs candidatas de calendario/resultados/tarjetas")
    print("#" * 100)
    for url in CANDIDATE_URLS:
        try:
            r = session.get(url, timeout=15, allow_redirects=True)
            print(f"  {url} -> status={r.status_code} final_url={r.url} bytes={len(r.text)}")
        except Exception as exc:
            print(f"  {url} -> ERROR {exc}")

    print()
    print("#" * 100)
    print("# 2) Dump crudo de la tabla 'Resultados' en la página del equipo")
    print("#" * 100)
    url = "https://fbf.com.bo/sport-team/always-ready/"
    r = session.get(url, timeout=25)
    soup = BeautifulSoup(r.text, "lxml")
    for table in soup.find_all("table"):
        heading = table.find_previous(["h1", "h2", "h3", "h4", "h5", "h6"])
        heading_text = heading.get_text(" ", strip=True) if heading else ""
        if "resultado" not in heading_text.lower():
            continue
        html = str(table)
        print(f"  heading='{heading_text}' outerHTML length={len(html)}")
        print(html[:4000])
        print("  ---- parent container (para ver contexto/hermanos) ----")
        parent = table.parent
        if parent:
            print(str(parent)[:4000])

    print()
    print("#" * 100)
    print("# 3) Buscar links de navegación que mencionen calendario/resultados/tarjetas")
    print("#" * 100)
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True).lower()
        href = a["href"].lower()
        if any(k in text or k in href for k in ["calendario", "resultado", "fixture", "tarjeta", "sancion", "disciplina", "partido"]):
            print(f"  '{a.get_text(' ', strip=True)}' -> {a['href']}")


if __name__ == "__main__":
    main()
