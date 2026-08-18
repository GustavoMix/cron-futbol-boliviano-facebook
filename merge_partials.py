from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path('.')
PART=ROOT/'partials'

def now_iso(): return datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
def load(path,default):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:return default

def ts(s):
    try:return datetime.fromisoformat((s or '').replace('Z','+00:00')).timestamp()
    except:return 0

def dedupe(items):
    d={}
    for x in items:
        key=x.get('post_id') or x.get('url') or x.get('id')
        if not key: continue
        prev=d.get(key)
        if prev is None or ts(x.get('scraped_at'))>=ts(prev.get('scraped_at')): d[key]=x
    return list(d.values())

def write(name,obj):
    Path(name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    fb=[]; fb_meta=[]
    for g in ('oficiales','clubes','medios'):
        p=PART/f'facebook_{g}.json'; data=load(p,{})
        fb.extend(data.get('items',[]));
        fb_meta.append({'group':g,'last_good_at':data.get('last_good_at'),'last_attempt_ok':data.get('last_attempt_ok'),'items':len(data.get('items',[]))})
    fb=dedupe(fb)
    cutoff=datetime.now(timezone.utc)-timedelta(days=7)
    keep=[]
    for x in fb:
        pub=x.get('published_at')
        if pub:
            try:
                if datetime.fromisoformat(pub.replace('Z','+00:00'))<cutoff: continue
            except: pass
        keep.append(x)
    fb=keep
    fb.sort(key=lambda x:(ts(x.get('published_at')),float(x.get('rank_score') or 0)),reverse=True)
    generated=now_iso()
    facebook_latest={'schema_version':5,'generated_at':generated,'groups':fb_meta,'items':fb[:300]}
    write('facebook_latest.json',facebook_latest)
    write('social.json',{'schema_version':5,'scope':'social','generated_at':generated,'items':fb[:300]})

    web_latest=load(PART/'web'/'latest.json',{}).get('items',[])
    combined=dedupe(web_latest+fb)
    combined.sort(key=lambda x:(float(x.get('rank_score') or 0),ts(x.get('published_at'))),reverse=True)
    write('latest.json',{'schema_version':5,'scope':'latest','generated_at':generated,'items':combined[:300]})
    write('app_feed.json',{'schema_version':5,'generated_at':generated,'items':combined[:300]})

    # Structured outputs stay sourced from web/official collector.
    for name in ('current_tables.json','bolivia.json','conmebol.json','internacional.json'):
        src=PART/'web'/name
        if src.exists():
            Path(name).write_bytes(src.read_bytes())

    web_manifest=load(PART/'web'/'manifest.json',{})
    manifest={
        'schema_version':5,
        'generated_at':generated,
        'architecture':'3 Facebook groups + 1 web group; staggered schedules; cached last-good Facebook data',
        'facebook_groups':fb_meta,
        'totals':{
            'facebook_items':len(fb),
            'web_latest_items':len(web_latest),
            'app_feed_items':min(300,len(combined)),
        },
        'web':{'generated_at':web_manifest.get('generated_at'),'totals':web_manifest.get('totals',{}),'errors':web_manifest.get('errors',[])},
        'notes':[
            'Facebook HTTP directo está desactivado.',
            'Se usa Chrome/Edge del sistema; Chromium de Playwright solo es fallback.',
            'Si un grupo Facebook falla temporalmente, no se borra el último JSON bueno.',
            'video_url directo puede caducar; post_url/video_post_url es la referencia estable.',
        ]
    }
    write('manifest.json',manifest)
    print(json.dumps(manifest['totals'],ensure_ascii=False,indent=2))

if __name__=='__main__': main()
