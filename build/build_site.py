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
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT_PATH = ROOT / "index.html"

SOURCE_LABELS = {
    "contracts": "Contracts",
    "campaign_finance": "Contributions",
    "lobbying": "Lobbying",
}

# Where a reader goes to check a number rather than take it on trust.
SOURCE_PROJECTS = {
    "contracts": ("../ne-contracts/", "Nebraska State Contracts"),
    "campaign_finance": ("../ne-campaign-finance/", "Nebraska Campaign Finance"),
    "lobbying": ("../ne-lobbying/", "Nebraska Lobbying"),
}


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

    grouped = defaultdict(list)
    for row in rows:
        grouped[row["entity_id"]].append(row)

    entities = []
    for entity_id, members in grouped.items():
        totals = defaultdict(lambda: {"records": 0, "amount": 0.0})
        aliases = {}
        for member in members:
            source = member["source"]
            totals[source]["records"] += int(member["records"] or 0)
            totals[source]["amount"] += float(member["amount"] or 0)
            # One row per distinct spelling, remembering where it was seen.
            aliases.setdefault(member["alias"], set()).add(source)

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
                "aliases": [
                    {"name": name, "sources": sorted(sources)}
                    for name, sources in sorted(aliases.items())
                ],
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


def render(entities, summary, coverage) -> str:
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

    source_links = " · ".join(
        f'<a href="{url}">{label}</a>' for url, label in SOURCE_PROJECTS.values()
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
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #14171a; --panel: #1c2025; --border: #2c323a; --text: #e6e9ed;
      --muted: #949dab; --accent: #ff6b6b; --accent-soft: #2a1c1d;
      --row-alt: #181c20; --shadow: 0 1px 3px rgba(0,0,0,.4);
      --contracts: #5aa9e6; --finance: #4cc38a; --lobbying: #b08cff;
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
  <input type="search" id="q" placeholder="Search an organization, or any of its name variants…" autocomplete="off">
  <select id="filter">
    <option value="">All entities</option>
    <option value="3">In all three record sets</option>
    <option value="2">In two or more</option>
    <option value="contracts">Has contracts</option>
    <option value="campaign_finance">Has contributions</option>
    <option value="lobbying">Has lobbying</option>
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
  <p>Sharing a normalized name does not make two records the same organization.
  Subsidiaries are not resolved to parents, and a national firm can share a name
  with an unrelated local one. Rows marked <span class="badge b-hard">ID</span>
  were joined by a source's own identifier rather than by name similarity, which
  is a stronger claim than the rest.</p>
  <p>Built {date.today().isoformat()} from <code>data/canonical_entities.csv</code>.
  Method, caveats and open work are in the
  <a href="https://github.com/diepjustin/diepjustin.github.io/tree/main/ne-connect">project README</a>.</p>
</footer>

<script>
const ENTITIES = {payload};
const LABELS = {json.dumps(SOURCE_LABELS)};
const ORDER = {json.dumps(list(SOURCE_LABELS))};

const money = n => n >= 1000000
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

function figures(e) {{
  return ORDER.filter(s => e.totals[s]).map(s => {{
    const t = e.totals[s];
    // Lobbying carries no dollar figure -- it is registered positions on bills.
    const value = s === 'lobbying'
      ? t.records.toLocaleString() + ' positions'
      : money(t.amount);
    return '<div class="fig">' + value + '<span>' + LABELS[s] + ' · ' +
      t.records.toLocaleString() + ' records</span></div>';
  }}).join('');
}}

function render(rows) {{
  count.textContent = rows.length.toLocaleString() + ' of ' +
    ENTITIES.length.toLocaleString() + ' entities';
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
    const aliases = e.aliases.map(a =>
      '<div class="alias"><b>' + esc(a.name) + '</b> — ' +
      a.sources.map(s => LABELS[s]).join(', ') + '</div>').join('');
    return '<div class="entity">' +
      '<div class="etop"><div class="ename">' + esc(e.name) + '</div>' +
      '<div class="badges">' + badges + '</div>' +
      '<div class="figs">' + figures(e) + '</div></div>' +
      '<div class="detail"><h4>Name variants folded into this entity</h4>' +
      aliases + '</div></div>';
  }}).join('');
}}

function apply() {{
  const term = q.value.trim().toLowerCase();
  const f = filter.value;
  render(ENTITIES.filter(e => {{
    if (f === '3' && e.sources.length < 3) return false;
    if (f === '2' && e.sources.length < 2) return false;
    if (f && f !== '2' && f !== '3' && !e.sources.includes(f)) return false;
    if (!term) return true;
    if (e.name.toLowerCase().includes(term)) return true;
    return e.aliases.some(a => a.name.toLowerCase().includes(term));
  }}));
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

    summary_path = DATA_DIR / "entities_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    html = render(entities, summary, lobbying_coverage())
    OUT_PATH.write_text(html, encoding="utf-8")

    print(f"  entities            {len(entities):>8,}")
    print(f"  in 2+ record sets   {sum(1 for e in entities if len(e['sources']) > 1):>8,}")
    print(f"  in all three        {sum(1 for e in entities if len(e['sources']) == 3):>8,}")
    print(f"  page size           {len(html.encode('utf-8')) / 1024:>8.0f} KB")
    print(f"  -> {OUT_PATH.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
