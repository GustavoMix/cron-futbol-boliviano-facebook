from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import yaml
from playwright.sync_api import sync_playwright

TZ_BO = timezone(timedelta(hours=-4))
MONTHS = {
    'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
    'julio':7,'agosto':8,'septiembre':9,'setiembre':9,'octubre':10,
    'noviembre':11,'diciembre':12,
}

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')

def clean(s: str) -> str:
    return re.sub(r'\s+', ' ', s or '').strip()


def clean_fb_post_text(text: str, page_name: str = "") -> str:
    """Quita nombre de página, tiempo relativo, reacciones y comentarios de UI."""
    t = clean(text)
    if page_name and t.lower().startswith(page_name.lower()):
        t = clean(t[len(page_name):])
    # Si el nombre visible difiere del configurado, corta el prefijo hasta el tiempo relativo.
    t = re.sub(r"^.{2,90}?\s+(?:\d+\s*(?:min|h|hora|horas|d|día|dias|días))\s*[·•-]\s*", "", t, flags=re.I)
    # Facebook suele dejar: "23 min · contenido..."
    t = re.sub(r"^(?:hace\s+)?\d+\s*(?:min|h|hora|horas|d|día|dias|días)\s*[·•-]?\s*", "", t, flags=re.I)
    t = re.sub(r"^(?:ahora|hace un momento)\s*[·•-]?\s*", "", t, flags=re.I)
    # Cortar antes de las reacciones/comentarios; todo lo posterior es ruido ajeno al post.
    for marker in ("Todas las reacciones:", "All reactions:", "Me gusta Comentar", "Like Comment", "Ver más comentarios"):
        pos = t.lower().find(marker.lower())
        if pos >= 0:
            t = t[:pos]
    t = re.sub(r"\s*…?\s*Ver más\s*$", "", t, flags=re.I)
    t = re.sub(r"\bYOUTUBE\.COM\b", " ", t, flags=re.I)
    t = re.sub(r"\b\d{1,2}:\d{2}\s*/\s*\d{1,2}:\d{2}\b", " ", t)
    t = re.sub(r"\s+\+\d+\s*$", "", t)
    t = re.sub(r"\s+", " ", t).strip(" ·-|—")
    return t


def fb_content_quality(text: str) -> float:
    probe = clean(text).lower()
    norm = re.sub(r"[^a-z0-9áéíóúñü ]+", " ", probe)
    high = (
        "clasific", "cuartos", "octavos", "resultado", "partido", "fecha", "gol", "victoria", "empate",
        "derrota", "fichaje", "refuerzo", "contrat", "lesion", "lesión", "baja", "sancion", "sanción",
        "convocad", "alineacion", "alineación", "arbitro", "árbitro", "designacion", "designación",
    )
    low = (
        "buenos dias", "buen día", "feliz cumple", "tienda", "camiseta", "abrígate", "abrigate",
        "sponsor", "promo", "promocion", "promoción", "venta de entradas", "entradas a la venta",
        "panini", "album", "álbum", "outlet",
    )
    score = 0.36 + min(0.14, len(probe) / 1200.0)
    if any(x in norm for x in high): score += 0.34
    if any(x in norm for x in low): score -= 0.50
    if re.search(r"\b(comienzo|inicia) (el )?(primer|segundo) tiempo\b", norm): score -= 0.20
    if "final de 45" in norm: score -= 0.55
    return round(max(0.0, min(1.0, score)), 4)


def short_title(text: str, limit: int = 150) -> str:
    t = clean(text)
    if len(t) <= limit:
        return t
    cut = t[:limit]
    for sep in ('. ', '! ', '? ', ' — '):
        idx = cut.rfind(sep)
        if idx >= 50:
            return cut[:idx + (1 if sep[0] in '.!?' else 0)].strip()
    return cut.rsplit(' ', 1)[0].strip() + '…'

def stable_id(*parts: str) -> str:
    raw='|'.join(clean(x) for x in parts)
    return hashlib.sha1(raw.encode('utf-8','ignore')).hexdigest()[:20]

def canonical_fb(url: str) -> str:
    if not url:
        return ''
    try:
        p=urlsplit(url)
        keep=[]
        for k,v in parse_qsl(p.query, keep_blank_values=True):
            if k in {'story_fbid','id'}:
                keep.append((k,v))
        return urlunsplit((p.scheme or 'https', p.netloc or 'www.facebook.com', p.path, urlencode(keep), ''))
    except Exception:
        return url

def post_id(url: str) -> str:
    for pat in (r'/posts/([^/?#]+)', r'/reel/([^/?#]+)', r'/videos/([^/?#]+)', r'[?&]story_fbid=([^&#]+)'):
        m=re.search(pat,url or '',re.I)
        if m:
            return m.group(1)
    return stable_id('fb',url)

def parse_fb_date(raw: str) -> str | None:
    raw=clean(raw)
    if not raw:
        return None
    low=raw.lower().replace('·',' ').strip()
    base=datetime.now(TZ_BO)
    if low in {'ahora','hace un momento','just now'}:
        return base.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
    patterns=[
        (r'(?:hace\s+)?(\d+)\s*(?:min|minuto|minutos)\b','minutes'),
        (r'(?:hace\s+)?(\d+)\s*(?:h|hora|horas)\b','hours'),
        (r'(?:hace\s+)?(\d+)\s*(?:d|dia|día|dias|días)\b','days'),
    ]
    for pat,unit in patterns:
        m=re.search(pat,low,re.I)
        if m:
            n=int(m.group(1))
            dt=base-timedelta(**{unit:n})
            return dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
    # "17 de abril de 2023" or "17 de abril"
    m=re.search(r'\b(\d{1,2})\s+de\s+([a-záéíóúñ]+)(?:\s+de\s+(\d{4}))?',low,re.I)
    if m:
        day=int(m.group(1)); mon=MONTHS.get(m.group(2)); year=int(m.group(3) or base.year)
        if mon:
            try:
                dt=datetime(year,mon,day,12,0,tzinfo=TZ_BO)
                if not m.group(3) and dt>base+timedelta(days=2):
                    dt=dt.replace(year=year-1)
                return dt.astimezone(timezone.utc).isoformat().replace('+00:00','Z')
            except ValueError:
                pass
    # 18/08/2026 etc
    m=re.search(r'\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b',low)
    if m:
        d,mo,y=map(int,m.groups()); y=y+2000 if y<100 else y
        try:
            return datetime(y,mo,d,12,0,tzinfo=TZ_BO).astimezone(timezone.utc).isoformat().replace('+00:00','Z')
        except ValueError:
            pass
    return None

def age_hours(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt=datetime.fromisoformat(iso.replace('Z','+00:00')).astimezone(timezone.utc)
        return round(max(0,(datetime.now(timezone.utc)-dt).total_seconds()/3600),2)
    except Exception:
        return None

def launch_browser(p):
    errors=[]
    # En GitHub ubuntu-latest usamos Google Chrome ya instalado.
    # No descargamos Chromium durante el workflow.
    channels=['msedge','chrome'] if os.name=='nt' else ['chrome']
    for channel in channels:
        try:
            b=p.chromium.launch(
                channel=channel,
                headless=True,
                args=['--disable-notifications','--disable-popup-blocking']
            )
            return b,channel,errors
        except Exception as e:
            errors.append(f'{channel}: {type(e).__name__}: {e}')
    # Falla rápido en vez de descargar un navegador pesado.
    return None,'',errors

JS_EXTRACT = r'''() => {
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
      if (!raw || raw.length>100) continue;
      if (/^(ahora|hace un momento|\d+\s*(min|h|d|sem))$/i.test(raw) || /\d{1,2}\s+de\s+[a-záéíóúñ]+/i.test(raw) || /^\d{1,2}[\/-]\d{1,2}[\/-]\d{2,4}$/i.test(raw)) dateCandidates.push(raw);
    }
    const imageCandidates=[];
    for (const im of box.querySelectorAll('img[src]')) {
      const src=im.currentSrc||im.src||'';
      if (!src || src.startsWith('data:')) continue;
      const w=im.naturalWidth||im.width||0, h=im.naturalHeight||im.height||0;
      const area=w*h;
      if (area < 12000) continue;
      imageCandidates.push({src,area,w,h,alt:(im.alt||'')});
    }
    imageCandidates.sort((a,b)=>b.area-a.area);
    const images=[];
    for (const x of imageCandidates) if (!images.some(y=>y.src===x.src)) images.push(x);
    const videos=[];
    for (const v of box.querySelectorAll('video,video source')) {
      const src=(v.currentSrc||v.src||v.getAttribute('src')||'').trim();
      if (src && !src.startsWith('blob:') && !src.startsWith('data:')) videos.push(src);
    }
    const posters=Array.from(box.querySelectorAll('video[poster]')).map(v=>v.poster).filter(Boolean);
    const type = href.includes('/reel/') ? 'reel' : (href.includes('/videos/') || videos.length || box.querySelector('video')) ? 'video' : images.length ? 'image' : 'text';
    rows.push({href,text,dateText:dateCandidates[0]||'',images:images.slice(0,6),videos:[...new Set(videos)].slice(0,3),posters:[...new Set(posters)].slice(0,3),mediaType:type});
  }
  return rows;
}'''

def scrape_group(config: dict, group: str) -> tuple[list[dict], list[dict]]:
    fb=config.get('facebook',{})
    specs=[s for s in fb.get('public_pages',[]) if s.get('group')==group]
    max_posts=int(fb.get('max_posts_per_page',8))
    scroll_rounds=int(fb.get('scroll_rounds',4))
    scroll_wait=int(fb.get('scroll_wait_ms',750))
    wait=int(fb.get('browser_wait_ms',1800))
    timeout=int(fb.get('browser_timeout_seconds',16))*1000
    recent=int(fb.get('recent_hours',72))
    out=[]; statuses=[]; seen=set()
    print(f'GRUPO: {group} | páginas: {len(specs)} | max {max_posts} posts/página | filtro {recent}h',flush=True)
    with sync_playwright() as p:
        browser,bname,launch_errors=launch_browser(p)
        if browser is None:
            raise RuntimeError('No se pudo iniciar Chrome/Edge: '+' | '.join(launch_errors[-2:]))
        print(f'Navegador: {bname} (sin descarga de Chromium si el sistema ya lo tiene)',flush=True)
        context=browser.new_context(locale='es-BO',viewport={'width':1280,'height':1800})
        page=context.new_page()
        for i,spec in enumerate(specs,1):
            name=spec.get('name','Facebook'); url=spec.get('url','').strip(); errors=[]
            print(f'[{i}/{len(specs)}] {name}',flush=True)
            if not url:
                statuses.append({'name':name,'ok':False,'items':0,'errors':['falta URL']}); continue
            try:
                print('      cargar ... ',end='',flush=True)
                page.goto(url.rstrip('/')+'/?sk=posts',wait_until='domcontentloaded',timeout=timeout)
                page.wait_for_timeout(wait)
                print('OK',flush=True)
                for label in ('Permitir todas las cookies','Allow all cookies','Aceptar todas las cookies'):
                    try:
                        btn=page.get_by_role('button',name=label)
                        if btn.count()>0:
                            btn.first.click(timeout=800); page.wait_for_timeout(300); break
                    except Exception:
                        pass
                for r in range(scroll_rounds):
                    try:
                        page.evaluate('window.scrollBy(0, Math.max(1000, window.innerHeight * 0.95))')
                        page.wait_for_timeout(scroll_wait)
                        print(f'      scroll {r+1}/{scroll_rounds} OK',flush=True)
                    except Exception as e:
                        errors.append(f'scroll: {type(e).__name__}: {e}'); break
                recs=page.evaluate(JS_EXTRACT)
                page_items=[]
                for rec in recs:
                    purl=canonical_fb(str(rec.get('href') or ''))
                    if not purl or purl in seen: continue
                    raw_text=clean(str(rec.get('text') or ''))
                    if len(raw_text)<20: continue
                    kws=[clean(str(k)).lower() for k in spec.get('keywords',[]) if clean(str(k))]
                    if kws and not any(k in raw_text.lower() for k in kws): continue
                    text=clean_fb_post_text(raw_text, name)
                    if len(text)<12: continue
                    content_quality=fb_content_quality(text)
                    published=parse_fb_date(str(rec.get('dateText') or ''))
                    age=age_hours(published)
                    if age is not None and age>recent: continue
                    ims=[]
                    for im in rec.get('images') or []:
                        src=str(im.get('src') or '')
                        if src.startswith('http'):
                            ims.append({'url':src,'width':im.get('w'),'height':im.get('h'),'alt':im.get('alt') or ''})
                    vids=[str(v) for v in rec.get('videos') or [] if str(v).startswith('http')]
                    posters=[str(v) for v in rec.get('posters') or [] if str(v).startswith('http')]
                    media_type=str(rec.get('mediaType') or 'text')
                    image_url=ims[0]['url'] if ims else (posters[0] if posters else '')
                    thumb=posters[0] if posters else image_url
                    direct_video=vids[0] if vids else ''
                    item={
                        'id': stable_id('facebook-browser',purl),
                        'kind':'social',
                        'platform':'facebook',
                        'post_id':post_id(purl),
                        'title':short_title(text),
                        'text':text,
                        'url':purl,
                        'post_url':purl,
                        'image_url':image_url,
                        'thumbnail_url':thumb,
                        'video_url':direct_video,
                        'video_post_url':purl if media_type in {'video','reel'} else '',
                        'media_type':media_type,
                        'published_at':published,
                        'scraped_at':now_iso(),
                        'source_id':'facebook_browser:'+re.sub(r'[^a-z0-9]+','_',name.lower()).strip('_'),
                        'source_name':'Facebook · '+name,
                        'source_type':'facebook_browser_public',
                        'source_authority':float(spec.get('authority',0.8)),
                        'scope':spec.get('scope','bolivia'),
                        'competition':spec.get('competition','general'),
                        'rank_score':round((1-(min(age or 0,recent)/recent))*0.72 + float(spec.get('authority',0.8))*0.28,4),
                        'stale':False,
                        'extra':{
                            'collector':'browser_public',
                            'page_name':name,
                            'page_url':url,
                            'group':group,
                            'age_hours':age,
                            'freshness_unknown':published is None,
                            'content_quality':content_quality,
                            'summary':text[:360],
                            'published_date':published[:10] if published else '',
                            'media':{'images':ims,'videos':vids,'posters':posters},
                            'direct_video_is_temporary':bool(direct_video),
                            'note_video':'La URL directa de video puede caducar; post_url/video_post_url es la referencia estable.',
                        },
                    }
                    page_items.append(item); seen.add(purl)
                    if len(page_items)>=max_posts: break
                out.extend(page_items)
                ok=len(page_items)>0
                print(f'      => {"OK" if ok else "SIN POSTS"} ({len(page_items)})',flush=True)
                statuses.append({'name':name,'url':url,'ok':ok,'items':len(page_items),'errors':errors})
            except Exception as e:
                msg=f'{type(e).__name__}: {e}'
                print('      => ERROR '+msg[:180],flush=True)
                statuses.append({'name':name,'url':url,'ok':False,'items':0,'errors':errors+[msg]})
        context.close(); browser.close()
    return out,statuses

def parse_iso(s):
    try:return datetime.fromisoformat((s or '').replace('Z','+00:00')).timestamp()
    except:return 0

def merge_with_previous(path: Path, new_items: list[dict], keep_days=7) -> tuple[list[dict], str|None]:
    old=[]; last_good=None
    if path.exists():
        try:
            data=json.loads(path.read_text(encoding='utf-8')); old=data.get('items',[]); last_good=data.get('last_good_at')
        except Exception: pass
    combined={}
    cutoff=datetime.now(timezone.utc)-timedelta(days=keep_days)
    for item in old+new_items:
        key=item.get('post_id') or item.get('url') or item.get('id')
        if not key: continue
        pub=item.get('published_at')
        if pub:
            try:
                if datetime.fromisoformat(pub.replace('Z','+00:00'))<cutoff: continue
            except: pass
        prev=combined.get(key)
        if prev is None or parse_iso(item.get('scraped_at'))>=parse_iso(prev.get('scraped_at')):
            combined[key]=item
    rows=list(combined.values())
    rows.sort(key=lambda x:(parse_iso(x.get('published_at')), float(x.get('rank_score') or 0)),reverse=True)
    if new_items: last_good=now_iso()
    return rows[:250],last_good

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--group',required=True,choices=['oficiales','clubes','medios'])
    ap.add_argument('--config',default='sources.yaml')
    ap.add_argument('--output-dir',default='partials')
    args=ap.parse_args()
    cfg=yaml.safe_load(Path(args.config).read_text(encoding='utf-8'))
    items,statuses=scrape_group(cfg,args.group)
    outdir=Path(args.output_dir); outdir.mkdir(parents=True,exist_ok=True)
    path=outdir/f'facebook_{args.group}.json'
    merged,last_good=merge_with_previous(path,items,keep_days=7)
    payload={
        'schema_version':5,
        'group':args.group,
        'generated_at':now_iso(),
        'last_attempt_ok':any(s.get('ok') for s in statuses),
        'last_good_at':last_good,
        'fresh_items_this_run':len(items),
        'items':merged,
        'sources':statuses,
    }
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    print('\nRESUMEN',flush=True)
    print(json.dumps({'group':args.group,'fresh_items':len(items),'saved_items':len(merged),'sources_ok':sum(1 for s in statuses if s.get('ok')),'sources_total':len(statuses)},ensure_ascii=False,indent=2),flush=True)
    # Never wipe good cache on a transient FB failure. Exit 0 so next scheduled group can continue.
    return 0

if __name__=='__main__':
    raise SystemExit(main())
