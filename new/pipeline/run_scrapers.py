"""Run scrapers and write data/dist/status.json.

Failures are recorded, never hidden. A source that fails keeps its last good
capture in place and is reported as stale to the site.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scrapers.base import REPO_ROOT, utc_now

DIST = REPO_ROOT / "data" / "dist"

# TODO(Phase 1+): register each scraper here as it is built.
#   from scrapers.contracts import ContractsScraper
#   REGISTRY = {"contracts": ContractsScraper}
REGISTRY: dict[str, type] = {}


def load_previous_status() -> dict:
    path = DIST / "status.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"sources": []}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", default="all")
    args = parser.parse_args()

    wanted = (
        list(REGISTRY)
        if args.sources == "all"
        else [s.strip() for s in args.sources.split(",") if s.strip()]
    )

    previous = {s["source"]: s for s in load_previous_status().get("sources", [])}
    results = []
    for name in wanted:
        cls = REGISTRY.get(name)
        if cls is None:
            print(f"unknown source: {name}")
            continue
        print(f"scraping {name}…")
        result = cls().execute()
        if not result["ok"]:
            # Carry the last good update forward so the banner can say how stale.
            prev = previous.get(name, {})
            result["last_good"] = prev.get("retrieved_at") or prev.get("last_good")
            print(f"  FAILED: {result['error']}")
        results.append(result)

    DIST.mkdir(parents=True, exist_ok=True)
    (DIST / "status.json").write_text(
        json.dumps({"built_at": utc_now(), "sources": results}, indent=2)
    )
    print(f"wrote {DIST / 'status.json'}")
    return 0 if all(r["ok"] for r in results) or not results else 1


if __name__ == "__main__":
    raise SystemExit(main())
