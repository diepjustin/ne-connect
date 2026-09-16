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
    # Not "Federal Contributions" yet: fec_contributions_ne.csv is header-only
    # today (indiv24.zip, 4.24 GB, deliberately not pulled -- PLAN.md Phase
    # 3). Label what's actually loaded; relabel once individual itemized
    # contributions land.
    "fec": "FEC Committees & Candidates",
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
    # No fec_amt column yet -- fec_contributions_ne.csv (the dollar figures)
    # is header-only until indiv24.zip is pulled, and a $0 column would
    # misleadingly assert "checked, found nothing" rather than "not loaded".
    "fec_recs",
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
  header {{ padding: 40px 20px 0; max-width: 900px; margin: 0 auto; }}
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
    max-width: 900px; margin: 0 auto; padding: 0 20px;
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
  #count {{ color: var(--muted); font-size: 12.5px; max-width: 900px; margin: 10px auto 4px; padding: 0 20px; }}
  main {{ max-width: 900px; margin: 0 auto; padding: 0 20px 60px; }}
  .entity {{ border-bottom: 1px solid var(--border); padding: 16px 4px; }}
  .etop {{ display: flex; align-items: baseline; gap: 12px; cursor: pointer; }}
  .chevron {{ flex: none; transition: transform .15s ease; opacity: .55; margin-top: 2px; }}
  .entity.open .chevron {{ transform: rotate(90deg); }}
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
  .detail {{ display: none; margin: 12px 0 0 26px; padding: 0 0 2px; font-size: 13.5px; max-width: 62ch; }}
  .entity.open .detail {{ display: block; }}
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
  .hint {{ color: var(--muted); font-size: 13px; padding: 14px 4px; }}
  footer {{
    max-width: 900px; margin: 0 auto; padding: 20px; border-top: 1px solid var(--border);
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

<main id="list"></main>

<footer>
  <p><strong>Read before quoting.</strong> Contract figures are award values
  summed across every year on record — not money paid — and about 4% of contract
  rows carry no dollar value at all, so an organization showing no contract total
  may still hold contracts. Contributions cover 2022–2026 only, the years
  Nebraska's current e-filing system spans, while contract records reach back
  further: the two halves of a row describe different periods.{coverage_note}</p>
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
const q = document.getElementById('q');
const pills = document.getElementById('pills');
const count = document.getElementById('count');
let currentFilter = '';

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
  return ORDER.filter(s => e.totals[s]).map(s => {{
    if (s === 'campaign_finance') return campaignFinanceFigures(e);
    const t = e.totals[s];
    // Disclosures have no dollar concept at all -- a C-1 reports interests
    // and relationships, not money. Item count only, never a "$0" that would
    // misleadingly imply nothing was disclosed.
    if (s === 'disclosures') {{
      return '<div class="fig">' + t.records.toLocaleString() +
        '<span>' + LABELS[s] + ' · items disclosed · self-reported</span></div>';
    }}
    // FEC: committees and candidates only today, no dollar figure at all --
    // individual itemized contributions (the actual money) aren't loaded
    // yet, so this is a record count same as disclosures, not $0.
    if (s === 'fec') {{
      return '<div class="fig">' + t.records.toLocaleString() +
        '<span>' + LABELS[s] + ' · FEC.gov record' +
        (t.records > 1 ? 's' : '') + '</span></div>';
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
  if (!rows.length) {{
    list.innerHTML = '<p class="hint">No entity matches that search.</p>';
    return;
  }}
  list.innerHTML = rows.map((e, idx) => {{
    // ORDER, not e.sources: the latter is alphabetical, which would put the
    // badges in a different order than the figures directly beside them.
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

    // Itemized records fetch lazily the first time this row opens -- fetching
    // ../ne-campaign-finance/d/rows.json (35+ MB) or ../ne-lobbying/d/positions.json
    // (11+ MB) for every entity up front would defeat the point of a lazy index.
    const txnsSlot = e.sources.includes('campaign_finance')
      ? '<div class="txns-slot cf-slot"></div>' : '';
    const posSlot = e.sources.includes('lobbying') && e.lobby_id
      ? '<div class="txns-slot pos-slot"></div>' : '';

    return '<div class="entity" data-idx="' + idx + '">' +
      '<div class="etop">' +
      '<svg class="chevron" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 6 15 12 9 18"/></svg>' +
      '<div class="ename">' + esc(e.name) + '</div>' +
      '<div class="badges">' + badges + '</div></div>' +
      '<div class="figs">' + figures(e) + '</div>' +
      '<div class="detail">' +
      '<h4>Why these records are grouped</h4>' + conf +
      '<h4>Name variants folded into this entity</h4>' + aliases +
      '<h4>Where each figure comes from</h4>' + prov +
      txnsSlot + posSlot +
      // PRIVACY: per-entity export only, per docs/PRIVACY.md rule 4 ("Per-search
      // CSV export is fine. A 'download all 240,000 contributors' button is
      // not.") -- never add a site-wide or filtered-list export button.
      '<button class="dl-btn" type="button">Download this entity as CSV</button>' +
      '</div></div>';
  }}).join('');
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
    totals.fec = {{records: row[COL.fec_recs], amount: 0}};
  }}
  const name = row[COL.name];
  const lobbyId = row[COL.lobby_id];
  const aliases = (row[COL.aliases] || []).map(n => ({{
    name: n, sources, url: '',
  }}));
  return {{
    name, sources, totals, contrib_eras: contribEras, aliases, match: null,
    hard_id: false, lite: true, lobby_id: lobbyId,
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
  if (!txns.length) return '';
  const rowsHtml = txns.slice(0, 200).map(t => {{
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
  }}).join('');
  const more = txns.length > 200
    ? '<p class="hint">' + (txns.length - 200).toLocaleString() + ' more not shown.</p>' : '';
  return '<h4>Itemized campaign-finance records</h4>' +
    '<table><tr><th>Date</th><th>Amount</th><th>To</th><th>City, State</th><th>Description</th></tr>' +
    rowsHtml + '</table>' + more;
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
  if (!positions.length) return '';
  const sorted = positions.slice().sort((a, b) => (b[0] + b[1]).localeCompare(a[0] + a[1]));
  const rowsHtml = sorted.slice(0, 200).map(p => {{
    const [legislature, bill, position, lobbyist] = p;
    const cls = POSITION_CLASS[position] || '';
    return '<tr><td>' + esc(legislature) + '</td><td>' + esc(bill) + '</td>' +
      '<td class="' + cls + '">' + esc(position) + '</td><td>' + esc(lobbyist) + '</td></tr>';
  }}).join('');
  const more = positions.length > 200
    ? '<p class="hint">' + (positions.length - 200).toLocaleString() + ' more not shown.</p>' : '';
  return '<h4>Registered lobbying positions</h4>' +
    '<table><tr><th>Legislature</th><th>Bill</th><th>Position</th><th>Lobbyist</th></tr>' +
    rowsHtml + '</table>' + more;
}}

// Per-entity export only -- see the PRIVACY comment at the button's markup.
// One flat CSV, a record_type column distinguishing rows shaped differently
// (a summary line, a name variant, an itemized transaction, a lobbying
// position) rather than one file per shape: a reporter dragging this into a
// spreadsheet gets everything about one name in one place.
const CSV_HEADER = [
  'entity', 'record_type', 'source', 'date', 'amount', 'records', 'recipient',
  'city_state', 'description', 'era', 'legislature', 'bill', 'position',
  'lobbyist', 'note',
];

function csvCell(v) {{
  const s = v === null || v === undefined ? '' : String(v);
  return /["\\n,]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
}}

function entityToCSVRows(e, cfTxns, positions) {{
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
        : s === 'fec' ? 'FEC.gov record, committees/candidates only' : '',
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

  (positions || []).forEach(p => {{
    const [legislature, bill, position, lobbyist] = p;
    push({{
      entity: e.name, record_type: 'lobbying_position', source: 'lobbying',
      legislature, bill, position, lobbyist,
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

list.addEventListener('click', ev => {{
  const dlBtn = ev.target.closest('.dl-btn');
  if (dlBtn) {{
    const row = dlBtn.closest('.entity');
    const e = row && renderedRows[Number(row.dataset.idx)];
    if (!e) return;
    const wantsCf = e.sources.includes('campaign_finance');
    const wantsPos = e.sources.includes('lobbying') && e.lobby_id;
    dlBtn.disabled = true;
    dlBtn.textContent = 'Preparing…';
    Promise.all([
      wantsCf ? loadCampaignFinanceRows() : Promise.resolve(null),
      wantsPos ? loadLobbyingPositions() : Promise.resolve(null),
    ]).then(([rowsData, positionsData]) => {{
      const cfTxns = rowsData ? campaignFinanceTxns(e, rowsData) : [];
      const positions = positionsData ? (positionsData[e.lobby_id] || []) : [];
      downloadCSV(slugify(e.name) + '.csv', entityToCSVRows(e, cfTxns, positions));
    }}).catch(() => {{
      downloadCSV(slugify(e.name) + '.csv', entityToCSVRows(e, [], []));
    }}).finally(() => {{
      dlBtn.disabled = false;
      dlBtn.textContent = 'Download this entity as CSV';
    }});
    return;
  }}

  const row = ev.target.closest('.entity');
  if (!row) return;
  const opening = !row.classList.contains('open');
  row.classList.toggle('open');
  if (!opening) return;
  const e = renderedRows[Number(row.dataset.idx)];
  if (!e) return;

  const cfSlot = row.querySelector('.cf-slot');
  if (cfSlot && !row.dataset.cfLoaded) {{
    row.dataset.cfLoaded = '1';
    cfSlot.textContent = 'Loading itemized records…';
    loadCampaignFinanceRows().then(rowsData => {{
      cfSlot.innerHTML = renderTxnTable(campaignFinanceTxns(e, rowsData));
    }}).catch(() => {{ cfSlot.textContent = 'Could not load itemized records.'; }});
  }}

  const posSlot = row.querySelector('.pos-slot');
  if (posSlot && !row.dataset.posLoaded) {{
    row.dataset.posLoaded = '1';
    posSlot.textContent = 'Loading registered positions…';
    loadLobbyingPositions().then(positionsData => {{
      posSlot.innerHTML = renderPositionsTable(positionsData[e.lobby_id] || []);
    }}).catch(() => {{ posSlot.textContent = 'Could not load registered positions.'; }});
  }}
}});
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

    summary_path = DATA_DIR / "entities_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    html = render(entities, summary, lobbying_coverage(), retrieval_dates(), len(full))
    OUT_PATH.write_text(html, encoding="utf-8")

    print(f"  searchable entities {len(full):>8,}  -> d/{INDEX_PATH.name}"
          f" ({INDEX_PATH.stat().st_size / 1024 / 1024:.2f} MB)")
    print(f"  inline, cross-source{len(entities):>8,}")
    print(f"  in all three        {sum(1 for e in entities if len(e['sources']) == 3):>8,}")
    print(f"  page size           {len(html.encode('utf-8')) / 1024:>8.0f} KB")
    print(f"  -> {OUT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
