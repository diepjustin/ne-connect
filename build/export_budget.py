"""Publish this project's own itemized budget/receipts artifacts.

Deliberately separate from build_site.py (already 1,500+ lines of HTML/JS
templating) and from build_entities.py (the resolution pipeline). This module
does neither -- it just reshapes two locally-cloned, read-only sibling repos'
CSVs into the small JSON files build_site.py's dossier panel and inline
General Fund Receipts section read.

Why this exists instead of following the "cross-fetch" pattern the other four
sources use (fetching a source's own already-published d/*.json at runtime):
nebraska-budget-data and nebraska-general-fund-receipts are NOT this project's
own repos -- they belong to a third party (the professor whose course this
project grew out of), with no live site of their own to fetch from and no
Pages this project can enable on someone else's repo. So this project's own
build publishes the itemized data instead. See docs/SCHEMA.md's
"Self-published" sections.

Usage:
    python build/export_budget.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingest"))

from sources import load_budget_rows, load_general_fund_receipts  # noqa: E402

OUT_DIR = ROOT / "d"


def write_budget_rows_json(out_path: Path = None) -> int:
    """d/budget_rows.json -- {display_name: [[fiscal_year, ...], ...]}, the
    same {name: [[row], ...]} shape convention as the cross-fetched
    d/rows.json / d/positions.json files, keyed by the SAME display name
    load_budget_subdivisions() uses (both call sources.py's shared
    _load_budget_groups()/_budget_name_collisions() pair) -- see
    docs/SCHEMA.md for the row shape.
    """
    out_path = out_path or (OUT_DIR / "budget_rows.json")
    rows_by_name = load_budget_rows()
    payload = json.dumps(rows_by_name, separators=(",", ":"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload, encoding="utf-8")
    return len(payload.encode("utf-8"))


def write_general_fund_receipts_json(out_path: Path = None) -> int:
    """d/gfr.json -- a documented, directly-linkable raw artifact for anyone
    who wants the full (release, fiscal-month) revision history. The page
    itself does NOT fetch this at runtime -- build_site.py inlines a
    collapsed (one row per calendar month, latest release only) copy
    directly into the page instead, since the section is meant to be visible
    on initial load, not gated behind a per-entity click like the itemized
    tables that DO fetch lazily.
    """
    out_path = out_path or (OUT_DIR / "gfr.json")
    rows = load_general_fund_receipts()
    payload = json.dumps(rows, separators=(",", ":"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(payload, encoding="utf-8")
    return len(payload.encode("utf-8"))


def latest_gfr_by_month() -> list:
    """One row per (data_year, data_month), keeping only the most recent
    release's figures -- the final, most-corrected value on record for that
    month. This is the collapsing step build_site.py inlines into the page;
    load_general_fund_receipts() itself stays an undecimated pass-through
    (see its docstring) so this project's own build, not the ingest adapter,
    decides what a compact always-visible table needs.
    Row: [fiscal_year, data_year, data_month_name, actual_net_receipts,
    projected_net_receipts, cumulative_actual_net_receipts,
    cumulative_projected_net_receipts], newest month first.
    """
    rows = load_general_fund_receipts()
    latest = {}
    for row in rows:
        (
            release_year, release_month, fiscal_year, data_year, data_month,
            data_month_name, actual, projected, cum_actual, cum_projected,
        ) = row
        key = (data_year, data_month)
        # rows is already newest-release-first (see load_general_fund_receipts'
        # own sort), so the first row seen per key is that month's latest release.
        if key not in latest:
            latest[key] = [
                fiscal_year, data_year, data_month_name,
                actual, projected, cum_actual, cum_projected,
            ]
    return [latest[key] for key in sorted(latest, reverse=True)]


def main() -> int:
    budget_bytes = write_budget_rows_json()
    gfr_bytes = write_general_fund_receipts_json()
    print(f"  d/budget_rows.json  {budget_bytes / 1024 / 1024:>8.2f} MB")
    print(f"  d/gfr.json          {gfr_bytes / 1024:>8.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
