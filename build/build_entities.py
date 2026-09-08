"""Phase 1: candidate matches, a review queue, and canonical entities.

Pipeline:
    normalize  ->  block on rare tokens  ->  score  ->  apply the human ledger
               ->  auto-accepted clusters  ->  canonical_entities.csv
               ->  everything uncertain   ->  review_queue.csv

Nothing is merged that a human has ruled against, and nothing involving a
person is auto-merged at all. The review queue is the product: it is ordered by
how much money is riding on the answer, so the most consequential judgement
calls come first.

Usage:
    python build/build_entities.py
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "resolve"))
sys.path.insert(0, str(ROOT / "ingest"))

from authority import short_circuit  # noqa: E402
from index import TokenIndex, candidate_pairs  # noqa: E402
from match import match_pair  # noqa: E402
from normalize import normalize_org  # noqa: E402
from resolutions import Ledger, UnionFind  # noqa: E402
from sources import (  # noqa: E402
    load_contract_vendors,
    load_contributors,
    load_lobbying_aliases,
    load_lobbying_principals,
)

DATA_DIR = ROOT / "data"
LEDGER_PATH = ROOT / "resolve" / "resolutions.csv"


def _keyed(parties):
    """raw name -> normalized key, dropping names that normalize to nothing."""
    keyed = {}
    for party in parties.values():
        normalized = normalize_org(party.name)
        if normalized:
            keyed.setdefault(normalized.key, []).append(party)
    return keyed


def _keyed_lobbying(principals, aliases):
    """One entry per (alias, principal) so every spelling reaches the index.

    A principal's truncated table name and its full detail-page name normalize
    to different keys. Both are registered, both carry the same source_id, and
    authority.py unions them without scoring.
    """
    import copy

    keyed = {}
    for source_id, party in principals.items():
        for alias in aliases.get(source_id, {party.name}) | {party.name}:
            normalized = normalize_org(alias)
            if not normalized:
                continue
            variant = copy.copy(party)
            variant.name = alias
            keyed.setdefault(normalized.key, []).append(variant)
    return keyed


def build(out_dir: Path = None, ledger_path: Path = None) -> dict:
    out_dir = out_dir or DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = Ledger.load(ledger_path or LEDGER_PATH)

    vendors = _keyed(load_contract_vendors())
    contributors = _keyed(load_contributors())
    lobbying_principals = load_lobbying_principals()
    lobbying = _keyed_lobbying(lobbying_principals, load_lobbying_aliases())

    # IDF is computed over ALL sources, so a token's rarity reflects the whole
    # corpus rather than whichever list happens to be largest.
    index = TokenIndex(list(vendors) + list(contributors) + list(lobbying))

    # Everything the authority pass can see. Contracts and campaign finance
    # publish no entity id, so in practice only lobbying contributes here --
    # but the pass is source-agnostic and will pick up any source that does.
    all_parties = {}
    for keyed in (vendors, contributors, lobbying):
        for key, parties in keyed.items():
            all_parties.setdefault(key, []).extend(parties)

    clusters = UnionFind()
    # PASS 1 -- identity that needs no scoring. Runs first so that a later name
    # match against any one alias attaches the entire id group.
    hard_links = short_circuit(clusters, all_parties)

    # Every pairing of sources gets scored. Lobbying joins contracts and campaign
    # finance by exact key for free -- identical keys are the same node -- but
    # near-misses ("NEBRASKA CATTLEMEN" vs "NEBRASKA CATTLEMEN ASSOCIATION")
    # need scoring like any other cross-source pair.
    matches = []
    seen_pairs = set()
    pairings = (
        ("contracts", vendors, "campaign_finance", contributors),
        ("contracts", vendors, "lobbying", lobbying),
        ("campaign_finance", contributors, "lobbying", lobbying),
    )
    for left_source, left_keyed, right_source, right_keyed in pairings:
        for left, right in candidate_pairs(left_keyed, right_keyed, index):
            # left == right is NOT skipped. An identical key appearing in two
            # sources is the strongest cross-source evidence there is, and it is
            # also how that key enters a cluster at all -- dropping it once took
            # auto-accepts from 453 to 0.
            pair = tuple(sorted((left, right)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            match = ledger.apply(
                match_pair(
                    left, right, index,
                    _dominant_type(left_keyed[left]), _dominant_type(right_keyed[right]),
                )
            )
            if match.decision == "reject":
                continue
            row = match.as_row()
            row.update(_money_columns(vendors.get(left, []), contributors.get(right, [])))
            row["left_source"] = left_source
            row["right_source"] = right_source
            row["vendor_names"] = " | ".join(sorted({p.name for p in left_keyed[left]}))
            row["contributor_names"] = " | ".join(sorted({p.name for p in right_keyed[right]}))
            matches.append(row)

    accepted = [m for m in matches if m["decision"] in ("auto", "accepted")]
    review = [m for m in matches if m["decision"] == "review"]

    # Most money riding on the answer, first.
    review.sort(key=lambda m: -(m["contribution_total"] + m["contract_total"]))
    accepted.sort(key=lambda m: -m["contribution_total"])

    # PASS 2 -- name-based matches, layered on top of the hard-id clusters.
    for match in accepted:
        clusters.union(match["left_key"], match["right_key"])

    entities = []
    for root, members in sorted(clusters.groups().items()):
        display_name = _canonical_name(members, vendors, contributors, lobbying)
        for member in sorted(members):
            for source, keyed in (
                ("contracts", vendors),
                ("campaign_finance", contributors),
                ("lobbying", lobbying),
            ):
                for party in keyed.get(member, []):
                    entities.append(
                        {
                            "entity_id": root,
                            "canonical_name": display_name,
                            "alias": party.name,
                            "normalized_key": member,
                            "source": source,
                            "role": party.role,
                            "entity_type": party.entity_type,
                            "records": party.record_count,
                            "amount": round(party.total_amount, 2),
                            "source_id": party.source_id,
                        }
                    )

    _write(out_dir / "hard_id_links.csv", hard_links)
    _write(out_dir / "match_candidates.csv", matches)
    _write(out_dir / "review_queue.csv", review)
    _write(out_dir / "canonical_entities.csv", entities)

    multi_source = sum(
        1
        for members in clusters.groups().values()
        if len({
            source
            for member in members
            for source, keyed in (("c", vendors), ("f", contributors), ("l", lobbying))
            if keyed.get(member)
        }) > 1
    )

    summary = {
        "built": date.today().isoformat(),
        "vendor_keys": len(vendors),
        "contributor_keys": len(contributors),
        "lobbying_keys": len(lobbying),
        "lobbying_principals": len(lobbying_principals),
        "hard_id_links": len(hard_links),
        "entities_in_two_or_more_sources": multi_source,
        "candidates_scored": len(matches),
        "auto_accepted": len(accepted),
        "awaiting_review": len(review),
        "human_decisions_on_record": len(ledger),
        "canonical_entities": len(clusters.groups()),
        "aliases": len(entities),
        "common_tokens_skipped": len(index.common_tokens),
    }
    (out_dir / "entities_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def _canonical_name(members, *keyed_sources) -> str:
    """The name to show for a cluster.

    Not the entity_id: that is the alphabetically-first normalized key, which
    for a lobbying entity is usually the TRUNCATED spelling ("ASSOCIATED
    BEVERAGE DISTRIBUTORS OF"). Prefer the longest alias the site did not cut
    short, so an entity is labelled with a name a reader can actually read.
    """
    aliases = [
        party.name
        for keyed in keyed_sources
        for member in members
        for party in keyed.get(member, [])
    ]
    if not aliases:
        return max(members, key=len).title()
    complete = [a for a in aliases if not a.rstrip().endswith("...")]
    return max(complete or aliases, key=len)


def _dominant_type(parties) -> str:
    return "individual" if any(p.entity_type == "individual" for p in parties) else "organization"


def _money_columns(vendor_parties, contributor_parties) -> dict:
    return {
        "contract_records": sum(p.record_count for p in vendor_parties),
        "contract_total": round(sum(p.total_amount for p in vendor_parties), 2),
        "contribution_records": sum(p.record_count for p in contributor_parties),
        "contribution_total": round(sum(p.total_amount for p in contributor_parties), 2),
    }


def _write(path: Path, rows) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    for label, value in build(out_dir=args.out).items():
        print(f"  {label:28} {value:>12,}" if isinstance(value, int) else f"  {label:28} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
