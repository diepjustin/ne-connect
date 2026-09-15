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
        for member in members:
            source = member["source"]
            totals[source]["records"] += int(member["records"] or 0)
            totals[source]["amount"] += float(member["amount"] or 0)
            if source == "campaign_finance":
                era = member.get("era") or "modern"
                era_totals[era]["records"] += int(member["records"] or 0)
                era_totals[era]["amount"] += float(member["amount"] or 0)
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

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Nebraska Public Records Hub</title>
<meta name="description" content="Organizations appearing across Nebraska state contracts, campaign finance and lobbying records, with links to the primary source for every figure.">
<style>
  :root {{
    --bg: #ffffff; --panel: #f6f7f9; --border: #d9dde3; --text: #14181d;
    --muted: #626b76; --accent: #d00000; --accent-soft: #fdecec;
    --row-alt: #fafbfc; --shadow: 0 1px 3px rgba(0,0,0,.08);
    --contracts: #0a6ebd; --finance: #1c7f4e; --lobbying: #7c4dd8;
    --disclosures: #b8860b; --fec: #a3315c;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #14171a; --panel: #1c2025; --border: #2c323a; --text: #e6e9ed;
      --muted: #949dab; --accent: #ff6b6b; --accent-soft: #2a1c1d;
      --row-alt: #181c20; --shadow: 0 1px 3px rgba(0,0,0,.4);
      --contracts: #5aa9e6; --finance: #4cc38a; --lobbying: #b08cff;
      --disclosures: #e0b23d; --fec: #e086a7;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  header {{ padding: 22px 20px 16px; border-bottom: 1px solid var(--border); }}
  h1 {{ margin: 0 0 4px; font-size: 21px; letter-spacing: -.01em; }}
  .sub {{ color: var(--muted); font-size: 13.5px; }}
  .sub p {{ margin: 0 0 6px; max-width: 82ch; }}
  .warn {{
    margin: 12px 0 0; padding: 10px 12px; max-width: 82ch;
    background: var(--accent-soft); border-left: 3px solid var(--accent);
    border-radius: 3px; font-size: 13.5px; color: var(--text);
  }}
  .warn strong {{ color: var(--accent); }}
  .stats {{
    display: flex; flex-wrap: wrap; gap: 8px; padding: 14px 20px;
    border-bottom: 1px solid var(--border); background: var(--panel);
  }}
  .stat {{
    background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
    padding: 8px 12px; min-width: 118px; box-shadow: var(--shadow);
  }}
  .stat b {{ display: block; font-size: 19px; letter-spacing: -.02em; }}
  .stat span {{ color: var(--muted); font-size: 12px; }}
  .controls {{
    display: flex; flex-wrap: wrap; gap: 10px; align-items: center;
    padding: 14px 20px; border-bottom: 1px solid var(--border);
  }}
  input[type=search], select {{
    font: inherit; padding: 7px 10px; border: 1px solid var(--border);
    border-radius: 4px; background: var(--bg); color: var(--text);
  }}
  input[type=search] {{ flex: 1 1 320px; }}
  #count {{ color: var(--muted); font-size: 13px; }}
  main {{ padding: 0 20px 60px; }}
  .entity {{ border-bottom: 1px solid var(--border); padding: 11px 8px; }}
  .entity:nth-child(even) {{ background: var(--row-alt); }}
  .etop {{
    display: flex; flex-wrap: wrap; gap: 6px 14px; align-items: baseline;
    cursor: pointer;
  }}
  .ename {{ font-weight: 600; flex: 1 1 240px; }}
  .badges {{ display: flex; gap: 5px; flex-wrap: wrap; }}
  .badge {{
    font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
    padding: 2px 7px; border-radius: 10px; border: 1px solid currentColor;
    white-space: nowrap;
  }}
  .b-contracts {{ color: var(--contracts); }}
  .b-campaign_finance {{ color: var(--finance); }}
  .b-lobbying {{ color: var(--lobbying); }}
  .b-disclosures {{ color: var(--disclosures); }}
  .b-fec {{ color: var(--fec); }}
  .b-hard {{ color: var(--muted); }}
  .figs {{
    display: flex; gap: 16px; flex-wrap: wrap;
    font-variant-numeric: tabular-nums; font-size: 13.5px;
  }}
  .fig span {{ color: var(--muted); font-size: 11.5px; display: block; }}
  .detail {{ display: none; padding: 10px 0 2px; font-size: 13.5px; }}
  .entity.open .detail {{ display: block; }}
  .detail h4 {{
    margin: 0 0 5px; font-size: 12px; text-transform: uppercase;
    letter-spacing: .05em; color: var(--muted); font-weight: 600;
  }}
  .alias {{ padding: 2px 0; color: var(--muted); }}
  .alias b {{ color: var(--text); font-weight: 500; }}
  .hint {{ color: var(--muted); font-size: 13px; padding: 14px 8px; }}
  footer {{
    padding: 20px; border-top: 1px solid var(--border);
    color: var(--muted); font-size: 13px;
  }}
  footer p {{ max-width: 82ch; margin: 0 0 8px; }}
  a {{ color: var(--accent); }}
</style>
</head>
<body>
<header>
  <h1>Nebraska Public Records Hub</h1>
  <div class="sub">
    <p>Organizations appearing in more than one Nebraska public record set —
    state contracts, campaign contributions, and lobbying registrations. Every
    figure comes from one of three collection projects:
    {source_links}.</p>
    <p>Names are matched by normalization and scoring; where a source publishes
    its own identifier, records are joined by that identifier instead. Select a
    row to see every spelling folded into it, and which record set each came from.</p>
    <div class="warn">
      <strong>A match is not a finding.</strong> Two records sharing a name is a
      reason to look, not a story. <strong>No person has confirmed any entity on
      this page.</strong> {summary.get('awaiting_review', 0):,} candidate pairs are
      still awaiting review, and {summary.get('human_decisions_on_record', 0)}
      human decisions are on record. Check the primary documents before
      publishing anything.
    </div>
  </div>
</header>

<div class="stats">
  <div class="stat"><b>{len(entities):,}</b><span>entities</span></div>
  <div class="stat"><b>{multi:,}</b><span>in 2+ record sets</span></div>
  <div class="stat"><b>{all_three:,}</b><span>in all three</span></div>
  <div class="stat"><b>{summary.get('aliases', 0):,}</b><span>name variants folded</span></div>
  <div class="stat"><b>{summary.get('hard_id_links', 0):,}</b><span>joined by source ID</span></div>
  <div class="stat"><b>{summary.get('awaiting_review', 0):,}</b><span>awaiting review</span></div>
</div>

<div class="controls">
  <input type="search" id="q" placeholder="Search an organization, or any of its name variants…" autocomplete="off" autofocus>
  <select id="filter">
    <option value="">All entities</option>
    <option value="3">In all three record sets</option>
    <option value="2">In two or more</option>
    <option value="contracts">Has contracts</option>
    <option value="campaign_finance">Has contributions</option>
    <option value="lobbying">Has lobbying</option>
    <option value="disclosures">Has a financial disclosure</option>
    <option value="fec">Has an FEC committee/candidate record</option>
  </select>
  <span id="count"></span>
</div>

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
const filter = document.getElementById('filter');
const count = document.getElementById('count');

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

function render(rows, pool) {{
  const scope = (pool || ENTITIES) === ENTITIES
    ? ENTITIES.length.toLocaleString() + ' cross-source entities'
    : TOTAL_INDEXED.toLocaleString() + ' entities';
  count.textContent = rows.length === 400
    ? 'first 400 matches in ' + scope
    : rows.length.toLocaleString() + ' of ' + scope;
  if (!rows.length) {{
    list.innerHTML = '<p class="hint">No entity matches that search.</p>';
    return;
  }}
  list.innerHTML = rows.map(e => {{
    // ORDER, not e.sources: the latter is alphabetical, which would put the
    // badges in a different order than the figures directly beside them.
    const badges = ORDER.filter(s => e.sources.includes(s)).map(s =>
      '<span class="badge b-' + s + '">' + LABELS[s] + '</span>').join('') +
      (e.hard_id ? '<span class="badge b-hard">ID</span>' : '');
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

    return '<div class="entity">' +
      '<div class="etop"><div class="ename">' + esc(e.name) + '</div>' +
      '<div class="badges">' + badges + '</div>' +
      '<div class="figs">' + figures(e) + '</div></div>' +
      '<div class="detail">' +
      '<h4>Why these records are grouped</h4>' + conf +
      '<h4>Name variants folded into this entity</h4>' + aliases +
      '<h4>Where each figure comes from</h4>' + prov +
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
    hard_id: false, lite: true,
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
  const f = filter.value;
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

list.addEventListener('click', ev => {{
  const row = ev.target.closest('.entity');
  if (row) row.classList.toggle('open');
}});
q.addEventListener('input', apply);
filter.addEventListener('change', apply);
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
