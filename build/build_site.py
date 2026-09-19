"""Build ne-connect/index.html from the canonical entity tables.

Same shape as ne-contracts/scripts/build_site.py: one hand-written HTML file
with inline CSS and an embedded JSON payload, no framework and no backend.
`index.html` sits at the folder root because that root is the published URL.

The payload is small here -- a few hundred KB against ne-contracts' 6.85 MB --
because this project publishes *entities*, not the millions of transactions
behind them. Every figure links back to the project that collected it.

What the page must never do is imply that a match is a finding. Nothing in
canonical_entities.csv has been confirmed by a person; the point of the review
queue is that the confirming has not happened yet. So the pending-review and
human-decision counts are rendered as prominently as the entity count itself,
not tucked into a footnote.
"""

from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingest"))

from export_fec import write_fec_rows_json  # noqa: E402

DATA_DIR = ROOT / "data"
OUT_PATH = ROOT / "index.html"
# The full index ships as its own file so the page opens instantly on the
# cross-source entities and only pays for the other 78,000 when someone
# searches. Measured rather than guessed: 2.97 MB raw, 0.86 MB over the wire
# once GitHub Pages gzips it -- about what the page already weighed, which is
# why this is one lazily-fetched file and not the 5,331 prefix buckets a
# three-character chunking scheme would have produced.
INDEX_DIR = ROOT / "d"
INDEX_PATH = INDEX_DIR / "entities.json"

# Bit 8 is reserved for SoS (PLAN.md Phase 2, blocked by nebraska.gov's terms
# of use -- see docs/DATA_SOURCES.md); the numbering is fixed so a later
# phase never has to shift an existing source's bit.
SOURCE_BITS = {
    "contracts": 1, "campaign_finance": 2, "lobbying": 4, "disclosures": 32, "fec": 16,
}

SOURCE_LABELS = {
    "contracts": "Contracts",
    "campaign_finance": "Contributions",
    "lobbying": "Lobbying",
    "disclosures": "Financial Disclosures",
    # Relabeled once indiv24/indiv26.zip were pulled and fec_contributions_ne.csv
    # stopped being header-only -- previously "FEC Committees & Candidates"
    # while there was no dollar figure to show at all.
    "fec": "FEC Contributions",
}

# Where a reader goes to check a number rather than take it on trust.
SOURCE_PROJECTS = {
    "contracts": ("../ne-contracts/", "Nebraska State Contracts"),
    "campaign_finance": ("../ne-campaign-finance/", "Nebraska Campaign Finance"),
    "lobbying": ("../ne-lobbying/", "Nebraska Lobbying"),
    "disclosures": ("../ne-campaign-finance/", "Nebraska Campaign Finance"),
    # ne-fec is local-only (no GitHub remote) by design -- link to the FEC's
    # own data front door instead, same "stopgap door" pattern as 0.7's NADC
    # search-page link.
    "fec": ("https://www.fec.gov/data/", "FEC"),
}

# d/entities.json header. Named, not positional-by-convention: every later
# phase (SoS, FEC) appends a column here and the JS reads it by name, so
# nothing about how existing columns are consumed has to change.
INDEX_COLUMNS = [
    "name", "bits", "contract_amt", "contract_recs",
    "contrib_amt", "contrib_recs", "lobby_recs", "lobby_id", "aliases",
    # Phase 1.4: pre-2022 campaign-finance money, tracked separately from
    # contrib_amt/contrib_recs (which are modern/2022+ only as of this
    # phase) -- the two eras are never summed into one figure.
    "contrib_amt_legacy", "contrib_recs_legacy",
    # Phase 1.5: disclosure filers, item count only -- a C-1 has no dollar
    # concept, so there is no disclosure_amt column.
    "disclosure_recs",
    # Phase 3: committees + candidates only, item count same as disclosures.
    "fec_recs",
    # disclosure_ids is a list, not a single id like lobby_id: one person can
    # file more than one disclosure (different years), each with its own
    # disclosure_id, all sharing one normalized-key entity.
    "disclosure_ids",
    # indiv24/indiv26.zip pulled -- fec_contributions_ne.csv is no longer
    # header-only, so there's a real dollar figure to carry. Appended last to
    # match build_full_index()'s append order -- see that function.
    "fec_amt",
]


def retrieval_dates():
    """When each source was last captured.

    UI_SPEC: a row without a retrieval date is a bug, and staleness is displayed
    rather than hidden. Read from each scraper's own metadata so the page cannot
    claim a freshness nobody verified.
    """
    dates = {}
    contracts_meta = ROOT.parent / "ne-contracts" / "data" / "scrape_meta.json"
    if contracts_meta.exists():
        stamps = [v[:10] for v in json.loads(contracts_meta.read_text()).values()]
        dates["contracts"] = max(stamps) if stamps else ""

    finance_meta = ROOT.parent / "ne-campaign-finance" / "data" / "scrape_meta.json"
    if finance_meta.exists():
        runs = json.loads(finance_meta.read_text())
        # Only the modern bulk-extract datasets are {year: [{"run_date": ...}]}
        # shaped (download_extracts.py's DATASETS). "legacy" (download_legacy.py)
        # is a single frozen capture with its own shape and is read separately,
        # not folded into this loop.
        stamps = [
            r["run_date"]
            for dataset in ("contributions", "expenditures")
            for rs in runs.get(dataset, {}).values()
            for r in rs
        ]
        dates["campaign_finance"] = max(stamps) if stamps else ""
        # Phase 1.4: the pre-2022 era is a one-time capture of a dataset the
        # state itself has stopped updating (see download_legacy.py), not a
        # recurring pull -- "retrieved" reads as misleadingly fresh without
        # saying so explicitly.
        legacy = runs.get("legacy") or {}
        if legacy.get("retrieved_at"):
            dates["campaign_finance_legacy"] = legacy["retrieved_at"]
            dates["campaign_finance_legacy_note"] = (
                "pre-2022 data frozen by the state as of 2022-07-11 -- "
                "this is a one-time capture, not a recurring pull"
            )

    lobbying_meta = ROOT.parent / "ne-lobbying" / "data" / "scrape_progress.json"
    if lobbying_meta.exists():
        dates["lobbying"] = json.loads(lobbying_meta.read_text()).get("last_run", "")

    # C-1 filings carry their own retrieved_at per row rather than a separate
    # scrape_meta.json -- read the newest one directly.
    c1_filings = ROOT.parent / "ne-campaign-finance" / "data" / "processed" / "c1_filings.csv"
    if c1_filings.exists():
        with c1_filings.open(encoding="utf-8", newline="") as fh:
            stamps = [row["retrieved_at"] for row in csv.DictReader(fh) if row.get("retrieved_at")]
        dates["disclosures"] = max(stamps) if stamps else ""
    # scrape_c1.py is deliberately not wired into ne-campaign-finance's daily
    # automation yet (PLAN.md item 1.6, a separate not-yet-built phase), so a
    # missing or header-only c1_filings.csv is the normal state today, not a
    # scraper failure. Without this, build_entities.py's disclosure_filer_keys:
    # 0 and this page's empty "Financial Disclosures" figures would look
    # exactly like "nobody in Nebraska has disclosed anything," which is not
    # what a zero here means. Fires whenever dates["disclosures"] came out
    # falsy above -- the key missing entirely (no file) or "" (file exists
    # but has no data rows) are the same gap, one check.
    if not dates.get("disclosures"):
        dates["disclosures_note"] = (
            "Financial disclosures (C-1/C-2 statements of financial "
            "interest) have not been collected yet -- the scraper that "
            "pulls them has not been wired into this project's automated "
            "runs. A name missing from this record set has not been "
            "checked against it, which is not the same as having nothing "
            "to disclose."
        )

    fec_meta = ROOT.parent / "ne-fec" / "data" / "scrape_meta.json"
    if fec_meta.exists():
        cycles = json.loads(fec_meta.read_text())
        stamps = [
            pull["retrieved_at"][:10]
            for cycle in cycles.values()
            for pull in cycle.values()
            if pull.get("retrieved_at")
        ]
        dates["fec"] = max(stamps) if stamps else ""
        # The fact that matters for the page isn't the CSV's row count (a
        # symptom) but this: no cycle here has ever recorded an "indiv" pull.
        # Read it from scrape_meta.json, not from fec_contributions_ne.csv
        # being empty, so this note survives even after a partial indiv pull
        # that a future run interrupts.
        if not any("indiv" in cycle for cycle in cycles.values()):
            dates["fec_note"] = (
                "committees and candidates only -- individual itemized "
                "contributions (indiv24.zip) have not been downloaded yet"
            )
        # Always shown once contributions exist, not gated on a data gap
        # like fec_note above: real-data measurement (2026-09-16) found 893
        # of 29,973 distinct contributor names carry more than one Nebraska
        # city across their records -- mostly the SAME person recorded
        # under a typo or a city-naming variant (e.g. Elkhorn/Omaha, merged
        # by annexation in 2007), sometimes two different people sharing a
        # name. FEC's bulk data carries no donor id to tell which, and
        # splitting by city would fragment real people's totals over a
        # typo more often than it would separate two real donors -- so
        # names are kept as FEC's own filings report them, with this
        # caveat surfaced rather than a false-precision fix.
        dates["fec_contributor_note"] = (
            "Individual contributions are grouped by the name in FEC's own "
            "filings. A shared name occasionally merges two different "
            "people; far more often it's one person recorded under a "
            "typo or a city-spelling variant across filings. FEC's bulk "
            "data carries no donor id to disambiguate further."
        )
    return dates


def match_reasons():
    """normalized key -> the scored reason it joined, for the UI.

    UI_SPEC: any match shown carries its score and the reason it matched. The
    scorer already writes both; they were simply not being rendered.
    """
    reasons = {}
    for row in read_csv(DATA_DIR / "match_candidates.csv"):
        if row.get("decision") not in ("auto", "accepted"):
            continue
        for key in (row["left_key"], row["right_key"]):
            current = reasons.get(key)
            if current is None or float(row["score"]) > current["score"]:
                reasons[key] = {
                    "score": float(row["score"]),
                    "reason": row.get("reason", ""),
                    "kind": row.get("match_kind", ""),
                }
    return reasons


def read_csv(path: Path):
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def build_entities():
    """canonical_entities.csv -> one record per entity, ready to embed."""
    rows = read_csv(DATA_DIR / "canonical_entities.csv")
    hard_id_keys = set()
    for link in read_csv(DATA_DIR / "hard_id_links.csv"):
        hard_id_keys.add(link["left_key"])
        hard_id_keys.add(link["right_key"])

    reasons = match_reasons()

    grouped = defaultdict(list)
    for row in rows:
        grouped[row["entity_id"]].append(row)

    entities = []
    for entity_id, members in grouped.items():
        # Single-source entities travel in the lazily-fetched index instead;
        # inlining all 79,021 would put 3 MB in front of every page load.
        if len({m["source"] for m in members}) < 2:
            continue
        totals = defaultdict(lambda: {"records": 0, "amount": 0.0})
        # Phase 1.4: campaign_finance is the only source with more than one
        # era today. Tracked separately from `totals` (which stays the
        # combined figure every other source already expects) so the two
        # eras can be rendered as two lines and never silently summed --
        # pre-2022 money and 2022+ money are not the same claim.
        era_totals = defaultdict(lambda: {"records": 0, "amount": 0.0})
        aliases = {}
        lobby_id = ""
        disclosure_ids = []
        for member in members:
            source = member["source"]
            totals[source]["records"] += int(member["records"] or 0)
            totals[source]["amount"] += float(member["amount"] or 0)
            if source == "campaign_finance":
                era = member.get("era") or "modern"
                era_totals[era]["records"] += int(member["records"] or 0)
                era_totals[era]["amount"] += float(member["amount"] or 0)
            if source == "lobbying" and member.get("source_id"):
                lobby_id = member["source_id"]
            if source == "disclosures" and member.get("source_id"):
                disclosure_ids.append(member["source_id"])
            # One row per distinct spelling, remembering where it was seen.
            aliases.setdefault(member["alias"], {"sources": set(), "url": ""})
            aliases[member["alias"]]["sources"].add(source)
            if member.get("source_url") and not aliases[member["alias"]]["url"]:
                aliases[member["alias"]]["url"] = member["source_url"]

        entities.append(
            {
                "id": entity_id,
                "name": members[0]["canonical_name"],
                "sources": sorted(totals),
                "totals": {
                    source: {
                        "records": value["records"],
                        "amount": round(value["amount"], 2),
                    }
                    for source, value in totals.items()
                },
                "contrib_eras": {
                    era: {"records": value["records"], "amount": round(value["amount"], 2)}
                    for era, value in era_totals.items()
                },
                "aliases": [
                    {"name": name, "sources": sorted(a["sources"]), "url": a["url"]}
                    for name, a in sorted(aliases.items())
                ],
                # The lobbying source's own principal id, when this entity has
                # one -- the join key for fetching ../ne-lobbying/d/positions.json,
                # same field name build_full_index() already uses for the lazy
                # index's lobby_id column.
                "lobby_id": lobby_id,
                # A list, not a single id: one person can file more than one
                # disclosure (different years), each its own disclosure_id,
                # all sharing this entity. Join key for
                # ../ne-campaign-finance/d/disclosure_items.json.
                "disclosure_ids": sorted(set(disclosure_ids)),
                "match": next(
                    (
                        reasons[m["normalized_key"]]
                        for m in members
                        if m["normalized_key"] in reasons
                    ),
                    None,
                ),
                # True when at least one alias was joined by a source-native id
                # rather than by name similarity. Worth surfacing separately:
                # it is a stronger kind of claim.
                "hard_id": any(m["normalized_key"] in hard_id_keys for m in members),
            }
        )

    # Most sources first, then the largest contract relationship.
    entities.sort(
        key=lambda e: (
            -len(e["sources"]),
            -e["totals"].get("contracts", {}).get("amount", 0),
            e["name"],
        )
    )
    return entities


def build_full_index(rows):
    """Every entity in one compact table, for search across all of them.

    {"columns": [...], "rows": [[...], ...]} rather than a bare array of
    objects: at 79,021 entities the key names would cost more than the values,
    but a bare positional array forces every reader to memorize an order that
    changes across phases. The header lets `widen()` read by name and lets a
    later phase append a column without touching how existing ones are read.

    `aliases` carries the *other* spellings folded into this entity -- empty
    for the ~76,000 entities with exactly one. `lobby_id` is the lobbying
    source's own principal id, present only where lobbying is one of the
    entity's sources.
    """
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["entity_id"]].append(row)

    index = []
    for members in grouped.values():
        bits = 0
        totals = defaultdict(lambda: [0, 0.0])
        # Phase 1.4: campaign_finance split by era so the lazy index can
        # render pre-2022 money separately, same reasoning as the inline
        # index's contrib_eras -- never summed into one figure.
        era_totals = defaultdict(lambda: [0, 0.0])
        lobby_id = ""
        disclosure_ids = []
        for member in members:
            bits |= SOURCE_BITS[member["source"]]
            totals[member["source"]][0] += int(member["records"] or 0)
            totals[member["source"]][1] += float(member["amount"] or 0)
            if member["source"] == "campaign_finance":
                era = member.get("era") or "modern"
                era_totals[era][0] += int(member["records"] or 0)
                era_totals[era][1] += float(member["amount"] or 0)
            if member["source"] == "lobbying" and member.get("source_id"):
                lobby_id = member["source_id"]
            if member["source"] == "disclosures" and member.get("source_id"):
                disclosure_ids.append(member["source_id"])
        contracts = totals["contracts"]
        finance_modern = era_totals["modern"]
        finance_legacy = era_totals["pre2022"]
        lobbying = totals["lobbying"]
        disclosures = totals["disclosures"]
        fec = totals["fec"]
        name = members[0]["canonical_name"]
        other_aliases = sorted({m["alias"] for m in members} - {name})
        index.append([
            name, bits,
            round(contracts[1]), contracts[0],
            round(finance_modern[1]), finance_modern[0],
            lobbying[0],
            lobby_id,
            other_aliases,
            round(finance_legacy[1]), finance_legacy[0],
            disclosures[0],
            fec[0],
            sorted(set(disclosure_ids)),
            round(fec[1]),
        ])
    index.sort(key=lambda e: (-bin(e[1]).count("1"), -e[2], e[0]))
    return index


def lobbying_coverage():
    """What the lobbying sweep actually covered, so the page can say so.

    The sweep is incomplete and the page must not imply otherwise, so this is
    read from the scraper's own checkpoint rather than asserted here.
    """
    progress = ROOT.parent / "ne-lobbying" / "data" / "scrape_progress.json"
    if not progress.exists():
        return None
    done = json.loads(progress.read_text()).get("done", [])
    if not done:
        return None
    return {
        "bills": len(done),
        "sessions": sorted({token.split("/")[0] for token in done}),
        "prefixes": sorted({token.split("/")[1][:2] for token in done}),
    }


def render(entities, summary, coverage, retrieved, total_indexed) -> str:
    payload = json.dumps(entities, separators=(",", ":"))
    multi = sum(1 for e in entities if len(e["sources"]) > 1)
    all_three = sum(1 for e in entities if len(e["sources"]) == 3)

    coverage_note = ""
    if coverage:
        coverage_note = (
            f" Lobbying coverage is <strong>partial</strong>: "
            f"{coverage['bills']:,} bills swept "
            f"({'/'.join(coverage['prefixes'])} only, "
            f"session {', '.join(coverage['sessions'])}). "
            "Completing the sweep would add entities and connections, not remove them."
        )

    # Same reasoning as coverage_note immediately above: retrieval_dates()
    # already detected that c1_filings.csv is missing/empty; say so in the
    # same disclaimer paragraph rather than letting the page's zero
    # disclosure figures pass as silence (CLAUDE.md: "reporters need to know
    # what they are looking at is stale").
    disclosures_note = ""
    if retrieved.get("disclosures_note"):
        disclosures_note = f" {retrieved['disclosures_note']}"

    # Dedupe by (url, label): disclosures shares ne-campaign-finance's project
    # link (same repo, different pipeline) rather than getting its own, so a
    # naive join would print "Nebraska Campaign Finance" twice.
    unique_projects = dict.fromkeys(SOURCE_PROJECTS.values())
    source_links = " · ".join(
        f'<a href="{url}">{label}</a>' for url, label in unique_projects
    )

    # Doubles as the source key: a reader can learn the five colors here
    # before ever seeing a badge in the list below.
    legend_html = "\n    ".join(
        f'<div class="legend-item"><span class="dot b-{key}"></span>{label}</div>'
        for key, label in SOURCE_LABELS.items()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nebraska Public Records Hub</title>
<meta name="description" content="Cross-reference a name across Nebraska state contracts, campaign contributions, lobbying registrations, financial disclosures, and federal campaign finance, with a link to the primary record behind every figure.">
<style>
  /* Editorial redesign, 2026-09-15 -- serif/sans pairing from system fonts
     only (Georgia, not a Google Fonts import): the footer below promises
     "no external fonts... nothing loads from a third party," which matters
     for a tool a source might search from. A harmonized five-color source
     palette (same lightness/chroma family, distinct hues) replaces the
     original ad hoc picks. */
  :root {{
    --bg: #faf8f4; --panel: #f2efe8; --border: #ddd6c8; --text: #211c14;
    --muted: #6b6252; --accent: #a1291f; --serif: Georgia, "Times New Roman", ui-serif, serif;
    --contracts: #3b6ea8; --finance: #3b8f63; --lobbying: #7a5fbf;
    --disclosures: #b08a2e; --fec: #b3486b;
    --support: #1c7f4e; --oppose: #b3261e; --neutral: #626b76;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #17140f; --panel: #201c15; --border: #383025; --text: #eee8db;
      --muted: #a89d88; --accent: #e2695c;
      --contracts: #7fb0e8; --finance: #7fce9e; --lobbying: #b79eec;
      --disclosures: #e0b764; --fec: #e58aa8;
      --support: #4cc38a; --oppose: #ff8a80; --neutral: #949dab;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  a {{ color: var(--accent); }}
  a:hover {{ color: var(--text); }}
  header {{ padding: 40px 20px 0; max-width: 1180px; margin: 0 auto; }}
  .kicker {{
    font: 600 11.5px/1 inherit; letter-spacing: .12em; text-transform: uppercase;
    color: var(--accent); margin: 0 0 14px;
  }}
  h1 {{
    font: 600 34px/1.15 var(--serif); margin: 0 0 14px; letter-spacing: -.01em;
    max-width: 15ch;
  }}
  .sub {{ color: var(--muted); font-size: 15px; }}
  .sub p {{ margin: 0 0 10px; max-width: 68ch; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 7px 16px; margin: 4px 0 22px; }}
  .legend-item {{ display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--muted); }}
  .dot {{ width: 9px; height: 9px; border-radius: 50%; flex: none; display: inline-block; }}
  .b-contracts {{ background: var(--contracts); }}
  .b-campaign_finance {{ background: var(--finance); }}
  .b-lobbying {{ background: var(--lobbying); }}
  .b-disclosures {{ background: var(--disclosures); }}
  .b-fec {{ background: var(--fec); }}
  .warn {{
    margin: 0 0 30px; padding: 13px 15px; max-width: 68ch;
    border: 1px solid var(--border); border-radius: 4px;
    font-size: 13.5px; color: var(--muted);
  }}
  .warn strong {{ color: var(--text); }}
  .stats {{
    display: flex; flex-wrap: wrap; gap: 26px; padding: 0 0 26px;
    border-bottom: 1px solid var(--border); margin-bottom: 22px;
  }}
  .stat b {{ display: block; font: 600 24px/1 var(--serif); letter-spacing: -.01em; }}
  .stat span {{
    display: block; margin-top: 4px; font-size: 11px; letter-spacing: .04em;
    text-transform: uppercase; color: var(--muted);
  }}
  .controls {{
    max-width: 1180px; margin: 0 auto; padding: 0 20px;
    display: flex; flex-wrap: wrap; gap: 10px 14px; align-items: center; margin-bottom: 8px;
  }}
  .search {{ position: relative; flex: 1 1 320px; }}
  .search svg {{ position: absolute; left: 11px; top: 50%; transform: translateY(-50%); opacity: .5; pointer-events: none; }}
  input[type=search] {{
    width: 100%; font: inherit; font-size: 15px; padding: 10px 12px 10px 34px;
    border: 1px solid var(--border); border-radius: 4px; background: var(--panel);
    color: var(--text);
  }}
  input[type=search]:focus {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
  .pills {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .pill {{
    font: 500 12.5px/1 inherit; padding: 7px 12px; border: 1px solid var(--border);
    border-radius: 20px; background: transparent; color: var(--muted); cursor: pointer;
  }}
  .pill.active {{ background: var(--text); color: var(--bg); border-color: var(--text); }}
  .pill-contracts.active {{ background: var(--contracts); border-color: var(--contracts); color: #fff; }}
  .pill-campaign_finance.active {{ background: var(--finance); border-color: var(--finance); color: #fff; }}
  .pill-lobbying.active {{ background: var(--lobbying); border-color: var(--lobbying); color: #fff; }}
  .pill-disclosures.active {{ background: var(--disclosures); border-color: var(--disclosures); color: #fff; }}
  .pill-fec.active {{ background: var(--fec); border-color: var(--fec); color: #fff; }}
  #count {{ color: var(--muted); font-size: 12.5px; max-width: 1180px; margin: 10px auto 4px; padding: 0 20px; }}
  .layout {{
    max-width: 1180px; margin: 0 auto; padding: 0 20px 60px;
    display: flex; gap: 24px; align-items: flex-start;
  }}
  #list {{ flex: 1 1 480px; min-width: 0; }}
  .entity {{ border-bottom: 1px solid var(--border); padding: 16px 4px; cursor: pointer; }}
  .entity:hover {{ background: var(--panel); }}
  .entity.selected {{ background: var(--panel); box-shadow: inset 3px 0 0 var(--accent); }}
  .etop {{ display: flex; align-items: baseline; gap: 12px; }}
  .ename {{ font: 600 17px/1.3 var(--serif); flex: 1 1 240px; }}
  .badges {{ display: flex; gap: 10px; flex-wrap: wrap; }}
  .src-badge {{ display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--muted); white-space: nowrap; }}
  .id-tag {{
    font-size: 10px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted);
    border: 1px solid var(--border); border-radius: 3px; padding: 1px 5px; white-space: nowrap;
  }}
  .figs {{
    display: flex; gap: 16px; flex-wrap: wrap; margin: 8px 0 0 26px;
    font-variant-numeric: tabular-nums; font-size: 13.5px;
  }}
  .fig span {{ color: var(--muted); font-size: 11.5px; display: block; }}
  /* Dossier panel, 2026-09-15 -- selecting an entity opens its full record
     here instead of expanding inline: a long inline expand-and-scroll was
     real reporter feedback ("annoying to scroll thru"). Sticky beside the
     list on desktop; a slide-up sheet on narrow screens (media query below). */
  .dossier {{
    flex: 1 1 380px; max-width: 420px; position: sticky; top: 20px;
    border: 1px solid var(--border); border-radius: 6px; background: var(--panel);
    max-height: calc(100vh - 40px); overflow-y: auto; padding: 20px 22px 26px;
  }}
  .dossier-empty {{ color: var(--muted); font-size: 13.5px; text-align: center; padding: 50px 10px; }}
  .dossier-name {{ font: 600 21px/1.25 var(--serif); margin: 2px 0 8px; }}
  .dossier .figs {{ margin-left: 0; margin-bottom: 4px; }}
  .dossier-close {{ display: none; }}
  .detail {{ margin: 14px 0 0; padding: 0 0 2px; font-size: 13.5px; }}
  .detail h4 {{
    margin: 14px 0 5px; font-size: 11px; text-transform: uppercase;
    letter-spacing: .05em; color: var(--muted); font-weight: 600;
  }}
  .detail h4:first-child {{ margin-top: 0; }}
  .alias {{ padding: 2px 0; color: var(--muted); }}
  .alias b {{ color: var(--text); font-weight: 500; }}
  .txns-slot table {{
    width: 100%; border-collapse: collapse; font-size: 12.5px; margin-top: 4px;
  }}
  .txns-slot th, .txns-slot td {{
    text-align: left; padding: 4px 8px 4px 0; border-bottom: 1px solid var(--border);
  }}
  .txns-slot td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .era-tag {{
    font-size: 9.5px; text-transform: uppercase; color: var(--muted);
    border: 1px solid var(--border); border-radius: 3px; padding: 0 3px; margin-left: 4px;
  }}
  .pos-s {{ color: var(--support); }}
  .pos-o {{ color: var(--oppose); }}
  .pos-x {{ color: var(--neutral); }}
  .dl-btn {{
    margin-top: 14px; font: 500 12.5px/1 inherit; padding: 7px 12px;
    border: 1px solid var(--border); border-radius: 4px; background: var(--panel);
    color: var(--text); cursor: pointer;
  }}
  .dl-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .txn-filter {{
    display: block; width: 100%; font: inherit; font-size: 13px;
    padding: 6px 9px; margin: 4px 0 6px; border: 1px solid var(--border);
    border-radius: 4px; background: var(--panel); color: var(--text);
  }}
  .txn-filter:focus {{ outline: 2px solid var(--accent); outline-offset: -1px; }}
  .txn-scroll {{
    max-height: 320px; overflow-y: auto; overflow-x: auto; border: 1px solid var(--border);
    border-radius: 4px;
  }}
  .txn-scroll table {{ margin-top: 0; }}
  .txn-scroll th {{ position: sticky; top: 0; background: var(--bg); }}
  .txn-scroll tr[hidden] {{ display: none; }}
  .txn-count {{ color: var(--muted); font-size: 11.5px; margin: 4px 0 0; }}
  .hint {{ color: var(--muted); font-size: 13px; padding: 14px 4px; }}
  .dossier-scrim {{
    position: fixed; inset: 0; background: rgba(0,0,0,.35); z-index: 49;
    opacity: 0; pointer-events: none; transition: opacity .2s ease;
  }}
  body.dossier-open .dossier-scrim {{ opacity: 1; pointer-events: auto; }}
  @media (min-width: 861px) {{ .dossier-scrim {{ display: none; }} }}
  @media (max-width: 860px) {{
    .layout {{ display: block; }}
    body.dossier-open {{ overflow: hidden; }}
    .dossier {{
      position: fixed; top: 8%; left: 0; right: 0; bottom: 0; z-index: 50;
      max-width: none; border-radius: 14px 14px 0 0; max-height: none;
      box-shadow: 0 -10px 30px rgba(0,0,0,.3);
      transform: translateY(100%); transition: transform .25s ease;
    }}
    .dossier.show {{ transform: translateY(0); }}
    .dossier-close {{
      display: block; position: absolute; top: 10px; right: 12px;
      font: 22px/1 inherit; background: none; border: none; color: var(--muted);
      cursor: pointer; padding: 4px 8px;
    }}
  }}
  footer {{
    max-width: 1180px; margin: 0 auto; padding: 20px; border-top: 1px solid var(--border);
    color: var(--muted); font-size: 13px;
  }}
  footer p {{ max-width: 68ch; margin: 0 0 8px; }}
</style>
</head>
<body>
<header>
  <p class="kicker">Nebraska Public Records Hub</p>
  <h1>One name. Every record.</h1>
  <div class="sub">
    <p>Cross-reference a name across Nebraska state contracts, campaign
    contributions, lobbying registrations, financial disclosures, and federal
    campaign finance &mdash; every figure links to the primary record and the
    date it was retrieved. Collected by {source_links}.</p>
    <p>Names are matched by normalization and scoring; where a source publishes
    its own identifier, records are joined by that identifier instead. Select a
    row to see every spelling folded into it, and which record set each came from.</p>
  </div>
  <div class="legend">
    {legend_html}
  </div>
  <div class="warn">
    <strong>A match is not a finding.</strong> Two records sharing a name is a
    reason to look, not a story. <strong>No person has confirmed any entity on
    this page.</strong> {summary.get('awaiting_review', 0):,} candidate pairs are
    still awaiting review, and {summary.get('human_decisions_on_record', 0)}
    human decisions are on record. Check the primary documents before
    publishing anything.
  </div>
  <div class="stats">
    <div class="stat"><b>{len(entities):,}</b><span>entities</span></div>
    <div class="stat"><b>{multi:,}</b><span>in 2+ record sets</span></div>
    <div class="stat"><b>{all_three:,}</b><span>in all three</span></div>
    <div class="stat"><b>{summary.get('aliases', 0):,}</b><span>name variants folded</span></div>
    <div class="stat"><b>{summary.get('hard_id_links', 0):,}</b><span>joined by source ID</span></div>
    <div class="stat"><b>{summary.get('awaiting_review', 0):,}</b><span>awaiting review</span></div>
  </div>
</header>

<div class="controls">
  <div class="search">
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
    <input type="search" id="q" placeholder="Search an organization, or any of its name variants…" autocomplete="off" autofocus>
  </div>
  <div class="pills" id="pills">
    <button class="pill active" data-f="">All entities</button>
    <button class="pill" data-f="3">In all three</button>
    <button class="pill" data-f="2">In two or more</button>
    <button class="pill pill-contracts" data-f="contracts">Contracts</button>
    <button class="pill pill-campaign_finance" data-f="campaign_finance">Contributions</button>
    <button class="pill pill-lobbying" data-f="lobbying">Lobbying</button>
    <button class="pill pill-disclosures" data-f="disclosures">Disclosures</button>
    <button class="pill pill-fec" data-f="fec">FEC</button>
  </div>
</div>
<p id="count"></p>

<div class="layout">
  <main id="list"></main>
  <aside class="dossier" id="dossier"></aside>
</div>
<div class="dossier-scrim" id="scrim"></div>

<footer>
  <p><strong>Read before quoting.</strong> Contract figures are award values
  summed across every year on record — not money paid — and about 4% of contract
  rows carry no dollar value at all, so an organization showing no contract total
  may still hold contracts. Contributions cover 2022–2026 only, the years
  Nebraska's current e-filing system spans, while contract records reach back
  further: the two halves of a row describe different periods.{coverage_note}{disclosures_note}</p>
  <p>Lobbying figures, where a dollar amount is shown, are a principal's own
  reported total from Form C &mdash; compensation, reimbursement, entertainment,
  lodging, travel, gifts and admissions &mdash; not audited spending. Form B,
  what a lobbyist reported receiving for the same work, is deliberately excluded:
  adding the two counts the same money twice. An entity showing positions but no
  amount has not had its expense reports collected yet, which is not the same as
  having spent nothing.</p>
  <p>Sharing a normalized name does not make two records the same organization.
  Subsidiaries are not resolved to parents, and a national firm can share a name
  with an unrelated local one. Rows marked <span class="badge b-hard">ID</span>
  were joined by a source's own identifier rather than by name similarity, which
  is a stronger claim than the rest.</p>
  <p>No analytics, no tracking, no external fonts, and nothing loads from a third
  party — searching a name here does not send it anywhere.</p>
  <p>Built {date.today().isoformat()} from <code>data/canonical_entities.csv</code>.
  Method, caveats and open work are in the
  <a href="https://github.com/diepjustin/diepjustin.github.io/tree/main/ne-connect">project README</a>.</p>
</footer>

<script>
const ENTITIES = {payload};          // cross-source, inline, shown by default
const TOTAL_INDEXED = {total_indexed};
const BITS = {{contracts: 1, campaign_finance: 2, lobbying: 4, disclosures: 32, fec: 16}};
let ALL = null;                      // the other ~78,000, fetched on first search
let loading = false;
const LABELS = {json.dumps(SOURCE_LABELS)};
const RETRIEVED = {json.dumps(retrieved)};
const PROJECTS = {json.dumps({k: v[0] for k, v in SOURCE_PROJECTS.items()})};
const ORDER = {json.dumps(list(SOURCE_LABELS))};
// One link template per source, applied to a lazily-loaded row. All three
// now point at a per-name search on that source's own project page --
// campaign_finance switched from the generic NADC search page once Phase 1.3
// shipped a real ?q= search at ../ne-campaign-finance/.
const SOURCE_LINK = {{
  contracts: name => '../ne-contracts/?q=' + encodeURIComponent(name),
  campaign_finance: name => '../ne-campaign-finance/?q=' + encodeURIComponent(name),
  lobbying: (name, lobbyId) => lobbyId
    ? 'https://nebraskalegislature.gov/lobbyist/view.php?link=view_principal&id=' + lobbyId
    : '',
  // No dedicated search page for disclosure filers yet -- ne-campaign-finance's
  // ?q= search only indexes contributors/filers, not C-1 disclosures. Empty
  // string falls back to PROJECTS.disclosures (the project's home page)
  // rather than link somewhere that would not actually find this name.
  disclosures: () => '',
  // No per-name search either -- fec.gov's own site would need the
  // committee/candidate id, which lazily-loaded rows don't currently carry.
  // Falls back to PROJECTS.fec (fec.gov/data/).
  fec: () => '',
}};

// Contract totals run past a billion -- Hawkins Construction alone is $1.28B
// across 14 years -- and "$1282.2M" is not a number anyone reads.
const money = n => n >= 1000000000
  ? '$' + (n / 1000000000).toFixed(2) + 'B'
  : n >= 1000000
    ? '$' + (n / 1000000).toFixed(1) + 'M'
    : '$' + Math.round(n).toLocaleString();

const list = document.getElementById('list');
const dossier = document.getElementById('dossier');
const scrim = document.getElementById('scrim');
const q = document.getElementById('q');
const pills = document.getElementById('pills');
const count = document.getElementById('count');
let currentFilter = '';
let selectedIdx = null;

function esc(s) {{
  return String(s).replace(/[&<>"]/g,
    c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}})[c]);
}}

// Phase 1.4: pre-2022 money and 2022+ money are never summed into one
// figure -- the state's own record of the older era is frozen and the two
// periods aren't the same claim. Two distinct eras render as two lines;
// one era (the common case today) renders exactly as before.
function campaignFinanceFigures(e) {{
  const eras = e.contrib_eras || {{}};
  const keys = Object.keys(eras);
  if (keys.length < 2) {{
    const t = e.totals.campaign_finance;
    return '<div class="fig">' + money(t.amount) + '<span>' + LABELS.campaign_finance +
      ' · ' + t.records.toLocaleString() + ' records · itemized only</span></div>';
  }}
  const ERA_LABEL = {{modern: '2022–present', pre2022: 'pre-2022, frozen by the state'}};
  return keys.sort().map(era => {{
    const t = eras[era];
    return '<div class="fig">' + money(t.amount) + '<span>' + LABELS.campaign_finance +
      ' (' + (ERA_LABEL[era] || era) + ') · ' + t.records.toLocaleString() +
      ' records · itemized only</span></div>';
  }}).join('');
}}

function figures(e) {{
  // A spend-only campaign-finance filer (load_spend_only_filers()) has 0
  // itemized receipts by construction -- a zero-valued totals object is
  // still truthy, so without this a filer with real spending but no
  // itemized receipts
  // would show a misleading "$0 · 0 records" instead of nothing at all
  // (its spending shows in the itemized table below regardless).
  return ORDER.filter(s => e.totals[s] && (e.totals[s].records || e.totals[s].amount)).map(s => {{
    if (s === 'campaign_finance') return campaignFinanceFigures(e);
    const t = e.totals[s];
    // Disclosures have no dollar concept at all -- a C-1 reports interests
    // and relationships, not money. Item count only, never a "$0" that would
    // misleadingly imply nothing was disclosed.
    if (s === 'disclosures') {{
      return '<div class="fig">' + t.records.toLocaleString() +
        '<span>' + LABELS[s] + ' · items disclosed · self-reported</span></div>';
    }}
    // FEC contributions carry a real dollar figure now (indiv24/indiv26.zip
    // pulled), but the caveat matters: filter_ne.py filters on the DONOR's
    // home state, so this is "Nebraskans giving to any federal committee,"
    // not "money given to a Nebraska candidate" -- and FEC's own itemization
    // floor is $200, not Nebraska's $250, so the two totals aren't directly
    // comparable.
    if (s === 'fec') {{
      return '<div class="fig">' + money(t.amount) +
        '<span>' + LABELS[s] + ' · ' + t.records.toLocaleString() + ' record' +
        (t.records > 1 ? 's' : '') +
        ' · FEC.gov, $200+ itemized · by Nebraska donor, any recipient' +
        '</span></div>';
    }}
    // Lobbying is counted in registered positions, and carries a dollar figure
    // only where the principal's Form C has been collected. An entity with no
    // figure has not been swept yet -- which is not the same as having spent
    // nothing, so it shows positions alone rather than $0.
    const value = s === 'lobbying'
      ? (t.amount ? money(t.amount) : t.records.toLocaleString() + ' positions')
      : money(t.amount);
    let note = '';
    if (s === 'lobbying' && t.amount) {{
      note = ' · ' + t.records.toLocaleString() + ' positions · self-reported';
      return '<div class="fig">' + value + '<span>' + LABELS[s] + note +
        '</span></div>';
    }}
    return '<div class="fig">' + value + '<span>' + LABELS[s] + ' · ' +
      t.records.toLocaleString() + ' records' + note + '</span></div>';
  }}).join('');
}}

let renderedRows = [];
function render(rows, pool) {{
  const scope = (pool || ENTITIES) === ENTITIES
    ? ENTITIES.length.toLocaleString() + ' cross-source entities'
    : TOTAL_INDEXED.toLocaleString() + ' entities';
  count.textContent = rows.length === 400
    ? 'first 400 matches in ' + scope
    : rows.length.toLocaleString() + ' of ' + scope;
  renderedRows = rows;
  // A re-filtered list invalidates whatever was selected (its index may now
  // point at a different entity, or the old one may not be in `rows` at
  // all) -- always fall back to the empty dossier state on re-render.
  resetDossier();
  if (!rows.length) {{
    // The disclosures pill can only ever show this -- see RETRIEVED.disclosures_note
    // (build_site.py's retrieval_dates()): when the source is missing entirely,
    // no entity anywhere carries the disclosures bit, so filtering to it always
    // empties the list. Say why, rather than a bare "no matches" that reads as
    // "nobody in Nebraska has disclosed anything."
    const gapNote = (currentFilter === 'disclosures' && RETRIEVED.disclosures_note)
      ? ' ' + esc(RETRIEVED.disclosures_note) : '';
    list.innerHTML = '<p class="hint">No entity matches that search.' + gapNote + '</p>';
    return;
  }}
  list.innerHTML = rows.map((e, idx) => {{
    // ORDER, not e.sources: the latter is alphabetical, which would put the
    // badges in a different order than the figures directly beside them.
    const badges = ORDER.filter(s => e.sources.includes(s)).map(s =>
      '<span class="src-badge"><span class="dot b-' + s + '"></span>' + LABELS[s] + '</span>').join('') +
      (e.hard_id ? '<span class="id-tag">ID</span>' : '');
    return '<div class="entity" data-idx="' + idx + '">' +
      '<div class="etop">' +
      '<div class="ename">' + esc(e.name) + '</div>' +
      '<div class="badges">' + badges + '</div></div>' +
      '<div class="figs">' + figures(e) + '</div>' +
      '</div>';
  }}).join('');
}}

// Dossier panel, 2026-09-15 -- selecting an entity opens its full record here
// (name variants, provenance, itemized tables, CSV export) instead of
// expanding inline under the row. Real reporter feedback on the old inline
// pattern: a long expand-in-place was "annoying to scroll thru." Sticky
// beside the list on desktop; a slide-up sheet on narrow screens (CSS above).
function dossierEmptyHtml() {{
  return '<div class="dossier-empty">Select an entity to see its full record.</div>';
}}

function resetDossier() {{
  selectedIdx = null;
  dossier.classList.remove('show');
  document.body.classList.remove('dossier-open');
  dossier.innerHTML = dossierEmptyHtml();
}}

function openDossier(idx) {{
  const e = renderedRows[idx];
  if (!e) return;
  selectedIdx = idx;
  [...list.children].forEach(row =>
    row.classList.toggle('selected', Number(row.dataset.idx) === idx));

  // UI_SPEC: confidence is always visible -- the ID/SCORED badge travels
  // into the dossier header too, not just the list row (which can scroll
  // out of view while the dossier stays put).
  const badges = ORDER.filter(s => e.sources.includes(s)).map(s =>
    '<span class="src-badge"><span class="dot b-' + s + '"></span>' + LABELS[s] + '</span>').join('') +
    (e.hard_id ? '<span class="id-tag">ID</span>' : '');

  const aliases = e.aliases.map(a => {{
    const label = '<b>' + esc(a.name) + '</b>';
    // Link straight to the state's own record where the source publishes one.
    const name = a.url
      ? '<a href="' + esc(a.url) + '" rel="noopener">' + label + '</a>'
      : label;
    return '<div class="alias">' + name + ' — ' +
      a.sources.map(s => LABELS[s]).join(', ') + '</div>';
  }}).join('');

  const prov = e.sources.map(s => {{
    const when = RETRIEVED[s] ? 'retrieved ' + RETRIEVED[s] : 'retrieval date unknown';
    // A lazily-loaded row carries a link straight to this name's own search
    // or record; an inline cross-source entity only has the source's home.
    const deepLink = e.lite && e.links && e.links[s];
    const href = deepLink || PROJECTS[s];
    const linkLabel = deepLink ? 'search this name' : 'source project';
    let line = '<div class="alias">' + LABELS[s] + ' — <a href="' + esc(href) +
      '" rel="noopener">' + linkLabel + '</a>, ' + when + '</div>';
    // Phase 1.4: an entity with pre-2022 campaign-finance money also gets
    // the frozen-data note, once, regardless of whether it also has
    // modern-era money.
    if (s === 'campaign_finance' && e.contrib_eras && e.contrib_eras.pre2022
        && RETRIEVED.campaign_finance_legacy_note) {{
      line += '<div class="alias">' + esc(RETRIEVED.campaign_finance_legacy_note) +
        '</div>';
    }}
    if (s === 'fec' && RETRIEVED.fec_note) {{
      line += '<div class="alias">' + esc(RETRIEVED.fec_note) + '</div>';
    }}
    if (s === 'fec' && RETRIEVED.fec_contributor_note) {{
      line += '<div class="alias">' + esc(RETRIEVED.fec_contributor_note) + '</div>';
    }}
    return line;
  }}).join('');

  // UI_SPEC: any match shown carries its score and the reason it matched.
  let conf;
  if (e.hard_id) {{
    conf = '<div class="alias">Joined by an identifier the source itself ' +
      'publishes — identity by construction, not name similarity.</div>';
  }} else if (e.match) {{
    conf = '<div class="alias">Score ' + e.match.score.toFixed(2) + ' — ' +
      esc(e.match.reason) + '</div>' +
      '<div class="alias">Machine-decided and unreviewed. No person has ' +
      'confirmed this grouping.</div>';
  }} else if (e.lite) {{
    conf = '<div class="alias">Single source; linking to that source\\'s ' +
      'search for this name.</div>';
  }} else {{
    conf = '<div class="alias">Single source; nothing was matched to it.</div>';
  }}

  // Itemized records fetch lazily the first time this entity's dossier opens
  // -- fetching ../ne-campaign-finance/d/rows.json (35+ MB) or
  // ../ne-lobbying/d/positions.json (11+ MB) for every entity up front would
  // defeat the point of a lazy index.
  const txnsSlot = e.sources.includes('campaign_finance')
    ? '<div class="txns-slot cf-slot"></div>' : '';
  // Same alias-guessing as cf-slot: a filer's raw name isn't distinguished
  // from a contributor's in this entity object, so this is tried for any
  // campaign_finance entity -- a miss in expenditures.json costs nothing.
  const spendSlot = e.sources.includes('campaign_finance')
    ? '<div class="txns-slot spend-slot"></div>' : '';
  const posSlot = e.sources.includes('lobbying') && e.lobby_id
    ? '<div class="txns-slot pos-slot"></div>' : '';
  const discSlot = e.sources.includes('disclosures') && e.disclosure_ids && e.disclosure_ids.length
    ? '<div class="txns-slot disc-slot"></div>' : '';
  const contractsSlot = e.sources.includes('contracts')
    ? '<div class="txns-slot contracts-slot"></div>' : '';
  // Same treatment for individuals and organizations as campaign_finance
  // already gets above -- neither source distinguishes the two in the
  // dossier today (see docs/PRIVACY.md rule 1, not yet enforced at this
  // layer for any source).
  const fecSlot = e.sources.includes('fec')
    ? '<div class="txns-slot fec-slot"></div>' : '';

  dossier.innerHTML =
    '<button class="dossier-close" type="button" aria-label="Close">&times;</button>' +
    '<div class="dossier-name">' + esc(e.name) + '</div>' +
    '<div class="badges">' + badges + '</div>' +
    '<div class="figs">' + figures(e) + '</div>' +
    '<div class="detail">' +
    '<h4>Why these records are grouped</h4>' + conf +
    '<h4>Name variants folded into this entity</h4>' + aliases +
    '<h4>Where each figure comes from</h4>' + prov +
    // Above the itemized tables on purpose -- those can run to hundreds of
    // scrollable rows, and the button got lost below them (real feedback:
    // a reporter scrolled past a long table and never found it).
    // PRIVACY: per-entity export only, per docs/PRIVACY.md rule 4 ("Per-search
    // CSV export is fine. A 'download all 240,000 contributors' button is
    // not.") -- never add a site-wide or filtered-list export button.
    '<button class="dl-btn" type="button">Download this entity as CSV</button>' +
    txnsSlot + spendSlot + posSlot + discSlot + contractsSlot + fecSlot +
    '</div>';
  dossier.classList.add('show');
  document.body.classList.add('dossier-open');

  if (e.sources.includes('campaign_finance')) {{
    const cfSlot = dossier.querySelector('.cf-slot');
    cfSlot.textContent = 'Loading itemized records…';
    loadCampaignFinanceRows().then(rowsData => {{
      cfSlot.innerHTML = renderTxnTable(campaignFinanceTxns(e, rowsData));
    }}).catch(() => {{ cfSlot.textContent = 'Could not load itemized records.'; }});

    const spendSlotEl = dossier.querySelector('.spend-slot');
    spendSlotEl.textContent = 'Loading campaign spending…';
    loadCampaignExpenditures().then(expendData => {{
      spendSlotEl.innerHTML = renderExpendituresTable(campaignExpenditures(e, expendData));
    }}).catch(() => {{ spendSlotEl.textContent = 'Could not load campaign spending.'; }});
  }}

  if (e.sources.includes('lobbying') && e.lobby_id) {{
    const posSlotEl = dossier.querySelector('.pos-slot');
    posSlotEl.textContent = 'Loading registered positions…';
    loadLobbyingPositions().then(positionsData => {{
      posSlotEl.innerHTML = renderPositionsTable(positionsData[e.lobby_id] || []);
    }}).catch(() => {{ posSlotEl.textContent = 'Could not load registered positions.'; }});
  }}

  if (e.sources.includes('disclosures') && e.disclosure_ids && e.disclosure_ids.length) {{
    const discSlotEl = dossier.querySelector('.disc-slot');
    discSlotEl.textContent = 'Loading disclosed items…';
    loadDisclosureItems().then(itemsData => {{
      discSlotEl.innerHTML = renderDisclosureItems(disclosureItems(e, itemsData));
    }}).catch(() => {{ discSlotEl.textContent = 'Could not load disclosed items.'; }});
  }}

  if (e.sources.includes('contracts')) {{
    const contractsSlotEl = dossier.querySelector('.contracts-slot');
    contractsSlotEl.textContent = 'Loading contracts and purchase orders…';
    loadContractRows(e).then(txns => {{
      contractsSlotEl.innerHTML = renderContractRows(txns);
    }}).catch(() => {{ contractsSlotEl.textContent = 'Could not load contracts.'; }});
  }}

  if (e.sources.includes('fec')) {{
    const fecSlotEl = dossier.querySelector('.fec-slot');
    fecSlotEl.textContent = 'Loading FEC contributions…';
    loadFecRows().then(rowsData => {{
      fecSlotEl.innerHTML = renderFecTable(fecTxns(e, rowsData));
    }}).catch(() => {{ fecSlotEl.textContent = 'Could not load FEC contributions.'; }});
  }}
}}

// The lazily-fetched index is {{columns, rows}}; widen each row, by column
// name, to the same shape the inline entities use so one render path serves
// both. Reading by name (not position) is what lets a later phase append a
// column here without this function having to change for the old ones.
let COL = null;
function widen(row) {{
  const bits = row[COL.bits];
  const sources = [];
  if (bits & BITS.contracts) sources.push('contracts');
  if (bits & BITS.campaign_finance) sources.push('campaign_finance');
  if (bits & BITS.lobbying) sources.push('lobbying');
  if (bits & BITS.disclosures) sources.push('disclosures');
  if (bits & BITS.fec) sources.push('fec');
  const totals = {{}};
  const contribEras = {{}};
  if (bits & BITS.contracts) {{
    totals.contracts = {{records: row[COL.contract_recs], amount: row[COL.contract_amt]}};
  }}
  if (bits & BITS.campaign_finance) {{
    // contrib_amt/contrib_recs are modern (2022+) only as of Phase 1.4;
    // contrib_amt_legacy/contrib_recs_legacy is pre-2022. Combined here into
    // totals.campaign_finance for callers that just want a bottom line, and
    // into contrib_eras for figures()' two-line rendering when both exist.
    const modernRecs = row[COL.contrib_recs], modernAmt = row[COL.contrib_amt];
    const legacyRecs = row[COL.contrib_recs_legacy] || 0, legacyAmt = row[COL.contrib_amt_legacy] || 0;
    totals.campaign_finance = {{records: modernRecs + legacyRecs, amount: modernAmt + legacyAmt}};
    if (modernRecs) contribEras.modern = {{records: modernRecs, amount: modernAmt}};
    if (legacyRecs) contribEras.pre2022 = {{records: legacyRecs, amount: legacyAmt}};
  }}
  if (bits & BITS.lobbying) {{
    totals.lobbying = {{records: row[COL.lobby_recs]}};
  }}
  if (bits & BITS.disclosures) {{
    totals.disclosures = {{records: row[COL.disclosure_recs], amount: 0}};
  }}
  if (bits & BITS.fec) {{
    totals.fec = {{records: row[COL.fec_recs], amount: row[COL.fec_amt] || 0}};
  }}
  const name = row[COL.name];
  const lobbyId = row[COL.lobby_id];
  const disclosureIds = row[COL.disclosure_ids] || [];
  const aliases = (row[COL.aliases] || []).map(n => ({{
    name: n, sources, url: '',
  }}));
  return {{
    name, sources, totals, contrib_eras: contribEras, aliases, match: null,
    hard_id: false, lite: true, lobby_id: lobbyId, disclosure_ids: disclosureIds,
    links: Object.fromEntries(sources.map(s => [s, SOURCE_LINK[s](name, lobbyId)])),
  }};
}}

async function ensureIndex() {{
  if (ALL || loading) return;
  loading = true;
  count.textContent = 'loading the full index…';
  try {{
    const res = await fetch('d/entities.json');
    const {{columns, rows}} = await res.json();
    COL = {{}};
    columns.forEach((c, i) => COL[c] = i);
    ALL = rows.map(widen);
  }} catch (err) {{
    ALL = [];
    count.textContent = 'could not load the full index';
  }}
  loading = false;
  apply();
}}

function apply() {{
  const term = q.value.trim().toLowerCase();
  const f = currentFilter;
  // No search term: show the cross-source entities, which are the point of the
  // hub and are already here. A search reaches every entity in every source.
  if (term && !ALL) {{ ensureIndex(); }}
  const pool = term && ALL ? ALL : ENTITIES;
  render(pool.filter(e => {{
    if (f === '3' && e.sources.length < 3) return false;
    if (f === '2' && e.sources.length < 2) return false;
    if (f && f !== '2' && f !== '3' && !e.sources.includes(f)) return false;
    if (!term) return true;
    if (e.name.toLowerCase().includes(term)) return true;
    return e.aliases.some(a => a.name.toLowerCase().includes(term));
  }}).slice(0, 400), pool);
}}

// ne-connect is the read-only join; ne-campaign-finance's own site owns the
// itemized transaction data. This fetches that site's already-published
// d/rows.json (same GitHub Pages deployment, not a third party) once and
// caches it, rather than duplicating ~117k modern + ~253k legacy rows into
// this project's own build. Fetched lazily, on first expand of any entity
// with campaign-finance records -- not on page load.
let CF_ROWS = null;
function loadCampaignFinanceRows() {{
  if (CF_ROWS) return Promise.resolve(CF_ROWS);
  return fetch('../ne-campaign-finance/d/rows.json').then(r => r.json())
    .then(j => {{ CF_ROWS = j; return j; }});
}}

const ORG_DETAIL_URL = 'https://nadc-e.nebraska.gov/PublicSite/SearchPages/OrganizationDetail.aspx?OrganizationID={{org_id}}';
const cfMoney = n => '$' + n.toLocaleString(undefined, {{maximumFractionDigits: 0}});

// Shared by every itemized table (contributions, spending, positions): a
// long flat dump was hard to navigate (real feedback -- hundreds of rows
// pushed the download button out of sight below them). This caps how many
// rows ever reach the DOM, but wraps them in a fixed-height, scrollable box
// with its own text filter (delegated listener below) instead of dumping
// them into the page's own scroll.
const ITEMIZED_ROW_CAP = 500;
function itemizedBlock(heading, headerCells, allRows, rowToHtml, filterPlaceholder) {{
  if (!allRows.length) return '';
  const shown = allRows.slice(0, ITEMIZED_ROW_CAP);
  const theadHtml = '<tr>' + headerCells.map(h => '<th>' + h + '</th>').join('') + '</tr>';
  const bodyHtml = shown.map(rowToHtml).join('');
  const capNote = allRows.length > ITEMIZED_ROW_CAP
    ? '<p class="hint">' + (allRows.length - ITEMIZED_ROW_CAP).toLocaleString() +
      ' more not shown -- download the CSV for the full list.</p>'
    : '';
  return '<h4>' + heading + '</h4>' +
    '<input type="text" class="txn-filter" placeholder="' + esc(filterPlaceholder) + '">' +
    '<div class="txn-scroll"><table>' + theadHtml + bodyHtml + '</table></div>' +
    '<p class="txn-count">' + shown.length.toLocaleString() + ' of ' +
    allRows.length.toLocaleString() + ' shown</p>' + capNote;
}}

// rows.json is keyed by the exact raw contributor name campaign-finance's
// own scraper recorded, which is not always this entity's canonical display
// name (a different source may have won that pick -- see build_entities.py
// _canonical_name()). Rather than tracking which alias belongs to which
// source, try every alias plus the display name as a lookup key: a name that
// was never a campaign-finance contributor simply matches nothing.
function campaignFinanceTxns(e, rowsData) {{
  const keys = new Set([e.name, ...e.aliases.map(a => a.name)]);
  const txns = [];
  keys.forEach(k => {{ (rowsData[k] || []).forEach(t => txns.push(t)); }});
  txns.sort((a, b) => (b[0] || '').localeCompare(a[0] || ''));
  return txns;
}}

function renderTxnTable(txns) {{
  return itemizedBlock(
    'Itemized campaign-finance records',
    ['Date', 'Amount', 'To', 'City, State', 'Description'],
    txns,
    t => {{
      const [dateStr, amount, filerName, orgId, city, state, desc, included, era] = t;
      const recipient = orgId
        ? '<a href="' + ORG_DETAIL_URL.replace('{{org_id}}', encodeURIComponent(orgId)) +
          '" target="_blank" rel="noopener">' + esc(filerName) + '</a>'
        : esc(filerName);
      const place = [city, state].filter(Boolean).join(', ');
      const legacyNote = era === 'pre2022' ? ' <span class="era-tag">pre-2022</span>' : '';
      const dim = included ? '' : ' style="opacity:.55" title="not counted toward the total -- see include_in_total"';
      return '<tr' + dim + '><td>' + esc(dateStr) + legacyNote + '</td><td class="n">' +
        cfMoney(amount) + '</td><td>' + recipient + '</td><td>' + esc(place) + '</td>' +
        '<td>' + esc(desc) + '</td></tr>';
    }},
    'Filter by recipient, city, or description…'
  );
}}

// Self-published, not cross-fetched: ne-fec has no site of its own to fetch
// from (see build/export_fec.py's docstring) -- this project's own build
// wrote d/fec_rows.json, so this is fetch('d/fec_rows.json'), not another
// repo's URL like every loadXRows() above it.
let FEC_ROWS = null;
function loadFecRows() {{
  if (FEC_ROWS) return Promise.resolve(FEC_ROWS);
  return fetch('d/fec_rows.json').then(r => r.json())
    .then(j => {{ FEC_ROWS = j; return j; }});
}}

// Same alias-try pattern as campaignFinanceTxns -- fec_rows.json is keyed by
// the raw name load_fec_contributors() recorded, not always this entity's
// canonical display name.
function fecTxns(e, rowsData) {{
  const keys = new Set([e.name, ...e.aliases.map(a => a.name)]);
  const txns = [];
  keys.forEach(k => {{ (rowsData[k] || []).forEach(t => txns.push(t)); }});
  txns.sort((a, b) => (b[0] || '').localeCompare(a[0] || ''));
  return txns;
}}

function renderFecTable(txns) {{
  return itemizedBlock(
    'Itemized FEC contributions',
    ['Date', 'Amount', 'Committee', 'City, State', 'Record'],
    txns,
    t => {{
      const [dateStr, amount, cmteName, city, state, sourceUrl] = t;
      const place = [city, state].filter(Boolean).join(', ');
      const record = sourceUrl
        ? '<a href="' + esc(sourceUrl) + '" target="_blank" rel="noopener">view filing</a>'
        : '';
      return '<tr><td>' + esc(dateStr) + '</td><td class="n">' + cfMoney(amount) +
        '</td><td>' + esc(cmteName) + '</td><td>' + esc(place) + '</td>' +
        '<td>' + record + '</td></tr>';
    }},
    'Filter by committee or city…'
  );
}}

// Same lazy, cache-once pattern as loadCampaignFinanceRows -- the spending
// side of the same site's data, a separate file since it's keyed by filer
// name, not contributor name.
let CF_EXPENDITURES = null;
function loadCampaignExpenditures() {{
  if (CF_EXPENDITURES) return Promise.resolve(CF_EXPENDITURES);
  return fetch('../ne-campaign-finance/d/expenditures.json').then(r => r.json())
    .then(j => {{ CF_EXPENDITURES = j; return j; }});
}}

function campaignExpenditures(e, expendData) {{
  const keys = new Set([e.name, ...e.aliases.map(a => a.name)]);
  const txns = [];
  keys.forEach(k => {{ (expendData[k] || []).forEach(t => txns.push(t)); }});
  txns.sort((a, b) => (b[0] || '').localeCompare(a[0] || ''));
  return txns;
}}

function renderExpendituresTable(txns) {{
  return itemizedBlock(
    'Campaign spending',
    ['Date', 'Amount', 'Paid to', 'City, State', 'Description'],
    txns,
    t => {{
      const [dateStr, amount, payeeName, desc, city, state, supportOppose, included, era] = t;
      const place = [city, state].filter(Boolean).join(', ');
      const legacyNote = era === 'pre2022' ? ' <span class="era-tag">pre-2022</span>' : '';
      const dim = included ? '' : ' style="opacity:.55" title="not counted toward the total -- see include_in_total"';
      const stance = supportOppose
        ? ' <span class="' + (POSITION_CLASS[supportOppose] || '') + '">' + esc(supportOppose) + '</span>'
        : '';
      return '<tr' + dim + '><td>' + esc(dateStr) + legacyNote + '</td><td class="n">' +
        cfMoney(amount) + '</td><td>' + esc(payeeName) + stance + '</td><td>' + esc(place) + '</td>' +
        '<td>' + esc(desc) + '</td></tr>';
    }},
    'Filter by payee, city, or description…'
  );
}}

// Same pattern as loadCampaignFinanceRows: ne-lobbying's own already-published
// d/positions.json, fetched once and cached, never duplicated into this build.
let LOBBY_POSITIONS = null;
function loadLobbyingPositions() {{
  if (LOBBY_POSITIONS) return Promise.resolve(LOBBY_POSITIONS);
  return fetch('../ne-lobbying/d/positions.json').then(r => r.json())
    .then(j => {{ LOBBY_POSITIONS = j; return j; }});
}}

const POSITION_CLASS = {{Support: 'pos-s', Oppose: 'pos-o', Neutral: 'pos-x'}};

// Unlike campaign finance, lobbying principals carry their own numeric id
// (e.lobby_id, same source_id build_entities.py already writes) -- an exact
// key into positions.json, no alias-guessing needed.
function renderPositionsTable(positions) {{
  const sorted = positions.slice().sort((a, b) => (b[0] + b[1]).localeCompare(a[0] + a[1]));
  return itemizedBlock(
    'Registered lobbying positions',
    ['Legislature', 'Bill', 'Position', 'Lobbyist'],
    sorted,
    p => {{
      const [legislature, bill, position, lobbyist] = p;
      const cls = POSITION_CLASS[position] || '';
      return '<tr><td>' + esc(legislature) + '</td><td>' + esc(bill) + '</td>' +
        '<td class="' + cls + '">' + esc(position) + '</td><td>' + esc(lobbyist) + '</td></tr>';
    }},
    'Filter by bill or lobbyist…'
  );
}}

// Same lazy, cache-once pattern -- financial-interest items, keyed by the
// state's own disclosure_id (an exact join key, no alias-guessing needed:
// e.disclosure_ids already carries every filing this entity has).
let DISCLOSURE_ITEMS = null;
function loadDisclosureItems() {{
  if (DISCLOSURE_ITEMS) return Promise.resolve(DISCLOSURE_ITEMS);
  return fetch('../ne-campaign-finance/d/disclosure_items.json').then(r => r.json())
    .then(j => {{ DISCLOSURE_ITEMS = j; return j; }});
}}

function disclosureItems(e, itemsData) {{
  const items = [];
  (e.disclosure_ids || []).forEach(id => {{ (itemsData[id] || []).forEach(it => items.push(it)); }});
  return items;
}}

// Real data-quality caveat (see ne-connect's load_disclosure_filers()
// docstring and docs/SCHEMA.md): a line-fallback parser on several item
// types can pick up the form's own instructional boilerplate as if it were
// the filer's answer, and most Manual filings are OCR'd from a scanned
// form. The state's own words either way (CLAUDE.md rule 1) -- never
// rewritten, just flagged for a reader's confidence.
function renderDisclosureItems(items) {{
  const block = itemizedBlock(
    'Financial-interest items disclosed',
    ['Item type', 'Named', 'Detail'],
    items,
    it => {{
      const [itemType, counterparty, detail, ocr, era] = it;
      const ocrNote = ocr ? ' <span class="era-tag">OCR</span>' : '';
      const legacyNote = era === 'pre2022' ? ' <span class="era-tag">pre-2022</span>' : '';
      return '<tr><td>' + esc(itemType.replace(/_/g, ' ')) + legacyNote + '</td><td>' +
        esc(counterparty) + ocrNote + '</td><td>' + esc(detail) + '</td></tr>';
    }},
    'Filter by name or detail…'
  );
  if (!block) return '';
  return block + '<p class="hint">Self-reported by the filer. Some rows are ' +
    'extracted by OCR from a scanned form and can be noisy, and a few item ' +
    'types occasionally pick up the form\\'s own instructions rather than a ' +
    'real answer -- verify against the original filing before quoting.</p>';
}}

// ne-contracts' export is sharded by the vendor name's first letter (one
// vendor alone -- Amazon Capital Services, ~66,900 line items -- made a
// combined file ~190 MB, past GitHub's 100 MB per-file push limit). This
// mirrors shard_key() in ne-contracts/scripts/export_vendor_rows.py; keep
// the two in sync. Shards are cached individually as they're fetched, not
// all 27 up front.
function contractShardKey(name) {{
  const first = (name || '').trim().slice(0, 1).toUpperCase();
  return (first >= 'A' && first <= 'Z') ? first : '_';
}}

const CONTRACT_SHARDS = {{}};
function loadContractShard(key) {{
  if (CONTRACT_SHARDS[key]) return CONTRACT_SHARDS[key];
  const p = fetch('../ne-contracts/d/rows/' + key + '.json').then(r => r.json())
    .catch(() => ({{}}));
  CONTRACT_SHARDS[key] = p;
  return p;
}}

// A cross-source entity's contract-side aliases can start with different
// letters (a renamed vendor, a DBA) -- fetch every shard any candidate name
// falls into, same alias-guessing reason as campaign finance's rows.json.
function loadContractRows(e) {{
  const keys = new Set([e.name, ...e.aliases.map(a => a.name)]);
  const shardKeys = new Set([...keys].map(contractShardKey));
  return Promise.all([...shardKeys].map(loadContractShard)).then(shardDatas => {{
    const txns = [];
    shardDatas.forEach(data => {{
      keys.forEach(k => {{ (data[k] || []).forEach(t => txns.push(t)); }});
    }});
    txns.sort((a, b) => (b[4] || '').localeCompare(a[4] || ''));
    return txns;
  }});
}}

function renderContractRows(txns) {{
  return itemizedBlock(
    'Itemized contracts and purchase orders',
    ['Document', 'Type', 'Agency', 'Amount', 'Begin', 'End', 'Status'],
    txns,
    t => {{
      const [docNumber, docType, entityName, amount, beginDate, endDate, status, detailUrl] = t;
      const doc = detailUrl
        ? '<a href="' + esc(detailUrl) + '" target="_blank" rel="noopener">' + esc(docNumber) + '</a>'
        : esc(docNumber);
      return '<tr><td>' + doc + '</td><td>' + esc(docType) + '</td><td>' + esc(entityName) +
        '</td><td class="n">' + cfMoney(amount) + '</td><td>' + esc(beginDate) + '</td>' +
        '<td>' + esc(endDate) + '</td><td>' + esc(status) + '</td></tr>';
    }},
    'Filter by agency, status, or document…'
  );
}}

// Per-entity export only -- see the PRIVACY comment at the button's markup.
// One flat CSV, a record_type column distinguishing rows shaped differently
// (a summary line, a name variant, an itemized transaction, a lobbying
// position) rather than one file per shape: a reporter dragging this into a
// spreadsheet gets everything about one name in one place.
const CSV_HEADER = [
  'entity', 'record_type', 'source', 'date', 'amount', 'records', 'recipient',
  'city_state', 'description', 'era', 'legislature', 'bill', 'position',
  'lobbyist', 'item_type', 'ocr', 'document_number', 'end_date', 'status',
  'note',
];

function csvCell(v) {{
  let s = v === null || v === undefined ? '' : String(v);
  // CSV/formula injection: several fields here are the state's own verbatim
  // text (a description, a payee name) that this project never rewrites --
  // if one happens to start with =, +, -, @, a tab or a CR, Excel/Sheets can
  // read it as a formula on open. Prefix with a bare quote so it opens as
  // text; the visible value is unchanged.
  if (/^[=+\\-@\\t\\r]/.test(s)) s = "'" + s;
  return /["\\n,]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}}

function entityToCSVRows(e, cfTxns, spending, positions, discItems, contractTxns, fecRows) {{
  const rows = [CSV_HEADER];
  const push = obj => rows.push(CSV_HEADER.map(col => obj[col] ?? ''));

  ORDER.filter(s => e.totals[s]).forEach(s => {{
    const eras = s === 'campaign_finance' ? (e.contrib_eras || {{}}) : {{}};
    if (Object.keys(eras).length > 1) {{
      Object.keys(eras).sort().forEach(era => {{
        const t = eras[era];
        push({{
          entity: e.name, record_type: 'summary', source: s, amount: t.amount,
          records: t.records, era, note: 'itemized only',
        }});
      }});
      return;
    }}
    const t = e.totals[s];
    push({{
      entity: e.name, record_type: 'summary', source: s,
      amount: t.amount || '', records: t.records,
      note: s === 'disclosures' ? 'items disclosed, self-reported'
        : s === 'lobbying' ? 'self-reported'
        : s === 'fec' ? 'FEC.gov, $200+ itemized, by Nebraska donor (any recipient)' : '',
    }});
  }});

  e.aliases.forEach(a => {{
    push({{
      entity: e.name, record_type: 'name_variant', recipient: a.name,
      note: a.sources.join('|'),
    }});
  }});

  (cfTxns || []).forEach(t => {{
    const [dateStr, amount, filerName, orgId, city, state, desc, included, era] = t;
    push({{
      entity: e.name, record_type: 'campaign_finance_transaction',
      source: 'campaign_finance', date: dateStr, amount, recipient: filerName,
      city_state: [city, state].filter(Boolean).join(', '), description: desc,
      era, note: included ? '' : 'excluded from the total (see include_in_total)',
    }});
  }});

  (spending || []).forEach(t => {{
    const [dateStr, amount, payeeName, desc, city, state, supportOppose, included, era] = t;
    push({{
      entity: e.name, record_type: 'campaign_finance_expenditure',
      source: 'campaign_finance', date: dateStr, amount, recipient: payeeName,
      city_state: [city, state].filter(Boolean).join(', '), description: desc,
      era, position: supportOppose,
      note: included ? '' : 'excluded from the total (see include_in_total)',
    }});
  }});

  (positions || []).forEach(p => {{
    const [legislature, bill, position, lobbyist] = p;
    push({{
      entity: e.name, record_type: 'lobbying_position', source: 'lobbying',
      legislature, bill, position, lobbyist,
    }});
  }});

  (discItems || []).forEach(it => {{
    const [itemType, counterparty, detail, ocr, era] = it;
    push({{
      entity: e.name, record_type: 'disclosure_item', source: 'disclosures',
      recipient: counterparty, description: detail, era, item_type: itemType,
      ocr: ocr ? 'true' : 'false',
    }});
  }});

  (contractTxns || []).forEach(t => {{
    const [docNumber, docType, entityName, amount, beginDate, endDate, status, detailUrl] = t;
    push({{
      entity: e.name, record_type: 'contract', source: 'contracts',
      date: beginDate, amount, recipient: entityName, description: docType,
      document_number: docNumber, end_date: endDate, status, note: detailUrl,
    }});
  }});

  (fecRows || []).forEach(t => {{
    const [dateStr, amount, cmteName, city, state, sourceUrl] = t;
    push({{
      entity: e.name, record_type: 'fec_contribution', source: 'fec',
      date: dateStr, amount, recipient: cmteName,
      city_state: [city, state].filter(Boolean).join(', '), note: sourceUrl,
    }});
  }});

  return rows;
}}

function slugify(name) {{
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'entity';
}}

function downloadCSV(filename, rows) {{
  const csv = rows.map(r => r.map(csvCell).join(',')).join('\\r\\n');
  const blob = new Blob([csv], {{type: 'text/csv;charset=utf-8;'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}}

// Selecting a row opens its dossier -- the itemized-loading and download
// logic all live on the dossier's own listeners below, since that's where
// those elements are now rendered.
list.addEventListener('click', ev => {{
  const row = ev.target.closest('.entity');
  if (!row) return;
  openDossier(Number(row.dataset.idx));
}});

dossier.addEventListener('click', ev => {{
  const closeBtn = ev.target.closest('.dossier-close');
  if (closeBtn) {{ resetDossier(); return; }}

  const dlBtn = ev.target.closest('.dl-btn');
  if (!dlBtn) return;
  const e = renderedRows[selectedIdx];
  if (!e) return;
  const wantsCf = e.sources.includes('campaign_finance');
  const wantsPos = e.sources.includes('lobbying') && e.lobby_id;
  const wantsDisc = e.sources.includes('disclosures') && e.disclosure_ids && e.disclosure_ids.length;
  const wantsContracts = e.sources.includes('contracts');
  const wantsFec = e.sources.includes('fec');
  dlBtn.disabled = true;
  dlBtn.textContent = 'Preparing…';
  Promise.all([
    wantsCf ? loadCampaignFinanceRows() : Promise.resolve(null),
    wantsCf ? loadCampaignExpenditures() : Promise.resolve(null),
    wantsPos ? loadLobbyingPositions() : Promise.resolve(null),
    wantsDisc ? loadDisclosureItems() : Promise.resolve(null),
    wantsContracts ? loadContractRows(e) : Promise.resolve(null),
    wantsFec ? loadFecRows() : Promise.resolve(null),
  ]).then(([rowsData, expendData, positionsData, itemsData, contractTxns, fecRowsData]) => {{
    const cfTxns = rowsData ? campaignFinanceTxns(e, rowsData) : [];
    const spending = expendData ? campaignExpenditures(e, expendData) : [];
    const positions = positionsData ? (positionsData[e.lobby_id] || []) : [];
    const items = itemsData ? disclosureItems(e, itemsData) : [];
    const fecRows = fecRowsData ? fecTxns(e, fecRowsData) : [];
    downloadCSV(slugify(e.name) + '.csv',
      entityToCSVRows(e, cfTxns, spending, positions, items, contractTxns || [], fecRows));
  }}).catch(() => {{
    downloadCSV(slugify(e.name) + '.csv', entityToCSVRows(e, [], [], [], [], [], []));
  }}).finally(() => {{
    dlBtn.disabled = false;
    dlBtn.textContent = 'Download this entity as CSV';
  }});
}});

// Filters one itemized table's rows in place, delegated so it works for
// tables injected later by the lazy fetches above.
dossier.addEventListener('input', ev => {{
  const inp = ev.target.closest('.txn-filter');
  if (!inp) return;
  const term = inp.value.trim().toLowerCase();
  const scroll = inp.nextElementSibling;
  const table = scroll && scroll.querySelector('table');
  if (!table) return;
  [...table.rows].forEach((tr, i) => {{
    if (i === 0) return; // header row
    tr.hidden = !!term && !tr.textContent.toLowerCase().includes(term);
  }});
}});

scrim.addEventListener('click', resetDossier);
pills.addEventListener('click', ev => {{
  const btn = ev.target.closest('.pill');
  if (!btn) return;
  currentFilter = btn.dataset.f;
  [...pills.children].forEach(b => b.classList.toggle('active', b === btn));
  apply();
}});
q.addEventListener('input', apply);
apply();
</script>
</body>
</html>
"""


def main() -> int:
    entities = build_entities()
    if not entities:
        print("no canonical entities on disk -- run build/build_entities.py first")
        return 1

    full = build_full_index(read_csv(DATA_DIR / "canonical_entities.csv"))
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    index_payload = {"columns": INDEX_COLUMNS, "rows": full}
    INDEX_PATH.write_text(json.dumps(index_payload, separators=(",", ":")), encoding="utf-8")

    fec_rows_bytes = write_fec_rows_json()

    summary_path = DATA_DIR / "entities_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    html = render(entities, summary, lobbying_coverage(), retrieval_dates(), len(full))
    OUT_PATH.write_text(html, encoding="utf-8")

    print(f"  searchable entities {len(full):>8,}  -> d/{INDEX_PATH.name}"
          f" ({INDEX_PATH.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"  fec_rows.json bytes {fec_rows_bytes:>8,}")
    print(f"  inline, cross-source{len(entities):>8,}")
    print(f"  in all three        {sum(1 for e in entities if len(e['sources']) == 3):>8,}")
    print(f"  page size           {len(html.encode('utf-8')) / 1024:>8.0f} KB")
    print(f"  -> {OUT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
