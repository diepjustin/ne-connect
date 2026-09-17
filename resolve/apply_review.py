"""Merge a browser review session's exported decisions into resolutions.csv.

pipeline/review.html (build/build_review_tool.py) lets a human click through
data/review_queue.csv and exports a CSV of what they decided:
`left_key,right_key,decision,note`. This module is the other half: it turns
those rows into real `Resolution` objects and folds them into the ledger,
reusing resolutions.py's existing `Resolution`/`Ledger`/`pair_id` machinery
verbatim -- no new hashing logic, no way for a decision to land under the
wrong pair_id.

`decided_by` is deliberately not part of the export (the browser tool never
asks who's using it) -- it's supplied once here, as `--by`, so one person's
name doesn't have to be typed hundreds of times in a review session.

Idempotent: `Resolution.pair_id` is deterministic, so re-running against the
same (or an overlapping) export overwrites those pairs in the ledger rather
than duplicating them.

Usage:
    python resolve/apply_review.py path/to/exported_decisions.csv --by "yourname"
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from resolutions import DIFFERENT, SAME, Ledger, Resolution

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "data" / "manual" / "resolutions.csv"

_DECISION_MAP = {"same": SAME, "different": DIFFERENT}


def load_decisions(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def apply_decisions(rows: list[dict], *, decided_by: str, ledger: Ledger) -> int:
    applied = 0
    for row in rows:
        raw_decision = (row.get("decision") or "").strip().lower()
        decision = _DECISION_MAP.get(raw_decision)
        if decision is None:
            continue
        ledger.add(
            Resolution(
                left_key=row["left_key"],
                right_key=row["right_key"],
                decision=decision,
                decided_by=decided_by,
                suggested_by="review",
                note=row.get("note", ""),
            )
        )
        applied += 1
    return applied


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decisions_csv", type=Path, help="pipeline/review.html's exported CSV")
    parser.add_argument("--by", required=True, dest="decided_by", help="who made these decisions")
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    args = parser.parse_args(argv)

    rows = load_decisions(args.decisions_csv)
    ledger = Ledger.load(args.ledger)
    before = len(ledger)
    applied = apply_decisions(rows, decided_by=args.decided_by, ledger=ledger)
    ledger.save(args.ledger)

    print(f"  {'decisions in export':28} {len(rows):>12,}")
    print(f"  {'applied to the ledger':28} {applied:>12,}")
    print(f"  {'ledger size (before -> after)':28} {before:>6,} -> {len(ledger):>6,}")
    print(
        "  rerun build/build_entities.py to drop these pairs from the next "
        "review_queue.csv"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
