"""Publish this project's own itemized FEC contribution rows.

Why this exists instead of the "cross-fetch" pattern the other four sources
use (fetching a source's own already-published d/*.json at runtime): ne-fec
has no site of its own to fetch from -- it publishes data files, not a
GitHub Pages deployment. So this project's own build reshapes ne-fec's
processed CSV into the small JSON the dossier panel reads. See
docs/SCHEMA.md's "Self-published" sections (this follows the same shape the
budgets/GFR work used).

Usage:
    python build/export_fec.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingest"))

from sources import load_fec_contribution_rows  # noqa: E402

OUT_DIR = ROOT / "d"


def write_fec_rows_json(out_path: Path = None) -> int:
    """d/fec_rows.json -- {raw_name: [[date, amount, cmte_name, city, state,
    source_url], ...]}, the same {name: [[row], ...]} shape convention as
    the cross-fetched d/rows.json / d/positions.json files, keyed by the
    same raw name load_fec_contributors() keys its Party objects by.
    """
    out_path = out_path or (OUT_DIR / "fec_rows.json")
    rows_by_name = load_fec_contribution_rows()
    payload = json.dumps(rows_by_name, separators=(",", ":"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload, encoding="utf-8")
    return len(payload.encode("utf-8"))


def main() -> int:
    size = write_fec_rows_json()
    print(f"  {'fec_rows.json bytes':28} {size:>12,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
