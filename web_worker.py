from __future__ import annotations
import json, tempfile
from pathlib import Path
import yaml
import main as core


def main():
    root=Path('.')
    cfg=yaml.safe_load((root/'sources.yaml').read_text(encoding='utf-8'))
    cfg.setdefault('facebook',{})['enabled']=False
    cfg.setdefault('x',{})['enabled']=False
    cfg.setdefault('youtube',{})['enabled']=False
    # Run web-only collector into partials/web.
    out=root/'partials'/'web'
    out.mkdir(parents=True,exist_ok=True)
    tmp=root/'partials'/'sources_web_runtime.yaml'
    tmp.write_text(yaml.safe_dump(cfg,allow_unicode=True,sort_keys=False),encoding='utf-8')
    manifest=core.run(tmp,out)
    try: tmp.unlink()
    except OSError: pass
    print(json.dumps(manifest.get('totals',{}),ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
