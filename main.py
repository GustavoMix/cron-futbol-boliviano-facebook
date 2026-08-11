from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from scraper.orchestrator import run


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Agregador de fútbol boliviano + CONMEBOL + redes sociales")
    parser.add_argument("--config", default="config/sources.yaml")
    parser.add_argument("--output", default="output")
    args = parser.parse_args()

    manifest = run(Path(args.config), Path(args.output))
    print(json.dumps(manifest["totals"], ensure_ascii=False, indent=2))
    if manifest["errors"]:
        print(f"Advertencias/errores: {len(manifest['errors'])}. Ver output/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
