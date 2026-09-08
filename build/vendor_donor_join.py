"""Phase 0: state vendors who are also campaign contributors.

The whole ne-connect bet in miniature. No scrapers, no site, no fuzzy matching
-- just deterministic normalization (resolve/normalize.py) and an exact join on
the resulting key, across two datasets that already exist.

If this produces a list that makes a reporter sit up, the rest of the project is
worth building. If it produces mush, that is worth knowing in days.

Every match carries a tier, and the tier is the honest part:

  strong   organization <-> organization on an exact normalized key. Two named
           businesses, same key. Still not proof they are one company -- see
           the caveats in the generated report -- but worth a look.
  weak     anything involving an individual, or a key short enough to collide
           by accident. Published, flagged, and NOT to be counted.

Nothing merges. This writes candidates for a human to review, which is the
whole design: resolutions.csv (phase 1) is where decisions get recorded.

Usage:
    python build/vendor_donor_join.py [--min-amount 0] [--out data/]
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "resolve"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingest"))

from normalize import normalize_org  # noqa: E402
from sources import load_contract_vendors, load_contributors  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "data"

# A key this short is a coincidence waiting to happen ("ACE", "K C"), so it is
# demoted regardless of what matched.
MIN_STRONG_KEY_LENGTH = 6
MIN_STRONG_TOKENS = 2


def match_tier(key: str, vendor_types, contributor_types) -> str:
    """How much weight this match can bear. See module docstring."""
    if "individual" in contributor_types or "individual" in vendor_types:
        return "weak"
    if len(key) < MIN_STRONG_KEY_LENGTH or len(key.split()) < MIN_STRONG_TOKENS:
        return "weak"
    return "strong"


def build(min_amount: float = 0.0, out_dir: Path = None) -> dict:
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    vendors = load_contract_vendors()
    contributors = load_contributors()

    by_key_vendors = defaultdict(list)
    for party in vendors.values():
        key = normalize_org(party.name)
        if key:
            by_key_vendors[key].append((party, key))

    by_key_contributors = defaultdict(list)
    for party in contributors.values():
        key = normalize_org(party.name)
        if key:
            by_key_contributors[key].append((party, key))

    matches = []
    for key in set(by_key_vendors) & set(by_key_contributors):
        vendor_parties = by_key_vendors[key]
        contributor_parties = by_key_contributors[key]

        contract_total = sum(p.total_amount for p, _ in vendor_parties)
        contribution_total = sum(p.total_amount for p, _ in contributor_parties)
        if contract_total < min_amount:
            continue

        # Show your work: the raw strings and the key they collapsed to. The
        # adopted normalizer does not emit a rule list, and the before/after
        # pair is the more checkable artifact anyway.
        rules = "; ".join(
            f"{p.name!r} -> {k}" for p, k in vendor_parties + contributor_parties
        )
        agencies = sorted({a for p, _ in vendor_parties for a in p.counterparties})
        recipients = sorted({c for p, _ in contributor_parties for c in p.counterparties})

        matches.append(
            {
                "normalized_key": key,
                "tier": match_tier(
                    key,
                    {p.entity_type for p, _ in vendor_parties},
                    {p.entity_type for p, _ in contributor_parties},
                ),
                "vendor_names": " | ".join(sorted({p.name for p, _ in vendor_parties})),
                "contributor_names": " | ".join(sorted({p.name for p, _ in contributor_parties})),
                "contract_records": sum(p.record_count for p, _ in vendor_parties),
                "contract_total": round(contract_total, 2),
                "contribution_records": sum(p.record_count for p, _ in contributor_parties),
                "contribution_total": round(contribution_total, 2),
                "agencies": len(agencies),
                "agencies_sample": " | ".join(agencies[:5]),
                "recipients": len(recipients),
                "recipients_sample": " | ".join(recipients[:5]),
                "normalization_applied": rules,
                "contract_url": next((p.sample_url for p, _ in vendor_parties if p.sample_url), ""),
            }
        )

    matches.sort(key=lambda m: (m["tier"] != "strong", -m["contribution_total"]))

    columns = list(matches[0].keys()) if matches else ["normalized_key"]
    with (out_dir / "vendor_donor_matches.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(matches)

    strong = [m for m in matches if m["tier"] == "strong"]
    summary = {
        "built": date.today().isoformat(),
        "distinct_vendors": len(vendors),
        "distinct_contributors": len(contributors),
        "vendor_keys": len(by_key_vendors),
        "contributor_keys": len(by_key_contributors),
        "matches": len(matches),
        "strong_matches": len(strong),
        "strong_contract_total": round(sum(m["contract_total"] for m in strong), 2),
        "strong_contribution_total": round(sum(m["contribution_total"] for m in strong), 2),
    }
    (out_dir / "vendor_donor_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-amount", type=float, default=0.0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    summary = build(min_amount=args.min_amount, out_dir=args.out)
    for label, value in summary.items():
        if isinstance(value, float):
            print(f"  {label:28} ${value:>18,.2f}")
        elif isinstance(value, int):
            print(f"  {label:28} {value:>19,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
