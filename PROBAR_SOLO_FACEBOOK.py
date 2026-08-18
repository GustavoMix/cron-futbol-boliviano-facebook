from pathlib import Path
import json
import yaml
from dotenv import load_dotenv
from main import HttpClient, scrape_facebook, classify, rank_item, utc_now_iso

load_dotenv()
cfg = yaml.safe_load(Path('sources.yaml').read_text(encoding='utf-8'))
settings = cfg.get('settings', {})
# Timeout corto para que una página no parezca congelar toda la prueba.
http = HttpClient(settings.get('user_agent', 'FutbolBoliviaAggregator/1.0'), timeout=8)
fb = cfg.get('facebook', {})
pages = fb.get('public_pages') or fb.get('page_queries', [])

print('============================================================', flush=True)
print(' PRUEBA FACEBOOK - FUTBOL BOLIVIANO - MODO VER TODO', flush=True)
print('============================================================', flush=True)
print(f'Paginas a probar: {len(pages)}', flush=True)
print('Cada intento HTTP tiene timeout corto; luego prueba Edge/Chrome.', flush=True)
print('No cierres la ventana: veras cada pagina en tiempo real.\n', flush=True)

items, errors = scrape_facebook(http, fb)
for x in items:
    classify(x)
    x.rank_score = rank_item(x)
payload = {
    'generated_at': utc_now_iso(),
    'facebook_items': len(items),
    'items': [x.to_dict() for x in items],
    'errors': errors,
}
Path('facebook_test.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

print('\n============================================================', flush=True)
print(' RESULTADO FINAL', flush=True)
print('============================================================', flush=True)
print(f'Posts Facebook encontrados: {len(items)}', flush=True)
if items:
    print('\nPrimeros posts:', flush=True)
    for x in items[:15]:
        print(f'- {x.source_name}: {x.title[:100]}', flush=True)
        print(f'  URL: {x.url}', flush=True)
        print(f'  FECHA: {x.published_at or x.extra.get("published_raw") or "sin fecha"}', flush=True)
        print(f'  MEDIA: {x.media_type} | imagen={"SI" if x.image_url else "NO"} | video_directo={"SI" if x.video_url else "NO"}', flush=True)
        if x.image_url: print(f'  IMG: {x.image_url[:180]}', flush=True)
        if x.video_url: print(f'  VIDEO: {x.video_url[:180]}', flush=True)
if errors:
    print(f'\nAdvertencias/errores: {len(errors)}', flush=True)
    for e in errors[:30]:
        print('  *', e, flush=True)
print('\nDetalle completo guardado en: facebook_test.json', flush=True)
