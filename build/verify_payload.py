"""Sanity-check a fresh build/build_entities.py + build/build_site.py run
before ne-connect-nightly.yml deploys it.

Fails loud only when a build looks *empty or broken* -- never merely because
one sibling's release came in a day late. CLAUDE.md's own rule already
covers staleness (build_site.py's retrieval_dates()/lobbying_coverage()
state what's actually on the page); this script exists for a different
failure mode entirely: a build that would silently publish nothing, or
silently drop a whole source, because a release download failed upstream.

Usage:
    python build/verify_payload.py [--previous path/to/previous_summary.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUMMARY_PATH = ROOT / "data" / "entities_summary.json"
ENTITIES_JSON_PATH = ROOT / "d" / "entities.json"
FEC_ROWS_PATH = ROOT / "d" / "fec_rows.json"

# Real builds have been in the 130,000+ range since FEC individual
# contributions landed -- a build below this floor is empty/broken by
# construction, no previous run needed to know something is badly wrong.
MIN_CANONICAL_ENTITIES = 50_000

# How far canonical_entities may drop from the previous run before this is
# treated as broken rather than ordinary day-to-day drift (e.g. a
# resolutions.csv merge shrinking the count a little is normal; a whole
# source vanishing is not).
MAX_DROP_FRACTION = 0.10

SOURCE_KEY_FIELDS = (
    "vendor_keys",
    "contributor_keys",
    "lobbying_keys",
    "disclosure_filer_keys",
    "fec_org_keys",
    "fec_contributor_keys",
)


def load_summary(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"missing {path} -- run build/build_entities.py first")
    return json.loads(path.read_text())


def check_entities_json(path: Path = ENTITIES_JSON_PATH) -> list[str]:
    problems = []
    if not path.exists():
        problems.append(f"{path} does not exist")
        return problems
    payload = json.loads(path.read_text())
    columns = payload.get("columns")
    rows = payload.get("rows")
    if not columns or not isinstance(rows, list):
        problems.append(f"{path} is missing the columns/rows shape")
        return problems
    if not rows:
        problems.append(f"{path} has zero rows")
        return problems
    width = len(columns)
    mismatched = sum(1 for row in rows[:1000] if len(row) != width)
    if mismatched:
        problems.append(
            f"{mismatched} of the first {min(1000, len(rows))} rows in {path} "
            f"don't match its {width}-column header"
        )
    return problems


def verify(
    summary: dict,
    previous: dict | None,
    *,
    entities_json_path: Path = None,
    fec_rows_path: Path = None,
) -> list[str]:
    # Defaults resolved here, not in the signature, so a caller (or a test)
    # overriding the module-level ENTITIES_JSON_PATH/FEC_ROWS_PATH constants
    # is actually picked up -- a default bound in the signature would freeze
    # at function-definition time and never see the override.
    entities_json_path = entities_json_path or ENTITIES_JSON_PATH
    fec_rows_path = fec_rows_path or FEC_ROWS_PATH
    problems = []

    canonical = summary.get("canonical_entities", 0)
    if canonical < MIN_CANONICAL_ENTITIES:
        problems.append(
            f"canonical_entities={canonical:,} is below the floor of "
            f"{MIN_CANONICAL_ENTITIES:,} -- this looks like an empty or badly broken build"
        )

    if previous:
        prev_canonical = previous.get("canonical_entities", 0)
        if prev_canonical and canonical < prev_canonical * (1 - MAX_DROP_FRACTION):
            problems.append(
                f"canonical_entities dropped from {prev_canonical:,} to {canonical:,} "
                f"(more than {MAX_DROP_FRACTION:.0%}) -- looks broken, not ordinary drift"
            )
        for field in SOURCE_KEY_FIELDS:
            prev_value = previous.get(field, 0)
            value = summary.get(field, 0)
            if prev_value > 0 and value == 0:
                problems.append(
                    f"{field} dropped from {prev_value:,} to 0 -- a whole source's "
                    "data looks missing from tonight's build, not just stale"
                )

    problems.extend(check_entities_json(entities_json_path))

    if fec_rows_path.exists() and fec_rows_path.stat().st_size < 1000:
        problems.append(
            f"{fec_rows_path} exists but is suspiciously small "
            f"({fec_rows_path.stat().st_size} bytes)"
        )

    return problems


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--previous", type=Path, default=None,
        help="a prior run's entities_summary.json to compare against (optional)",
    )
    args = parser.parse_args(argv)

    summary = load_summary(SUMMARY_PATH)
    previous = None
    if args.previous and args.previous.exists():
        previous = json.loads(args.previous.read_text())

    problems = verify(summary, previous)

    for field in ("canonical_entities", "entities_in_two_or_more_sources", *SOURCE_KEY_FIELDS):
        print(f"  {field:32} {summary.get(field, 0):>12,}")

    if problems:
        print("\nBUILD LOOKS BROKEN:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print("\nbuild looks healthy" + (" (no previous run to compare against)" if previous is None else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
