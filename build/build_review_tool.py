"""Build the local, human-only review-queue reviewer.

Not part of the published site. index.html is served from the repo root by
GitHub Pages, so this writes to pipeline/ instead (gitignored, see
.gitignore's comment) -- pipeline/review.html would otherwise publish the
entire *unreviewed* candidate list, including every individual x individual
name-collision guess, right alongside the finished site.

Read-only over data/review_queue.csv; never touches resolutions.csv. See
resolve/apply_review.py for the other half -- merging what a human decided
in the generated page back into the ledger.

Usage:
    python build/build_review_tool.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ingest"))

from build_site import SOURCE_PROJECTS  # noqa: E402

DATA_DIR = ROOT / "data"
QUEUE_PATH = DATA_DIR / "review_queue.csv"
OUT_DIR = ROOT / "pipeline"
OUT_PATH = OUT_DIR / "review.html"

_NUMERIC_COLUMNS = (
    "score",
    "key_weight",
    "contract_records",
    "contract_total",
    "contribution_records",
    "contribution_total",
)


def load_queue(path: Path = None) -> list[dict]:
    path = path or QUEUE_PATH
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        for col in _NUMERIC_COLUMNS:
            try:
                row[col] = float(row.get(col) or 0)
            except ValueError:
                row[col] = 0
    return rows


def render(rows: list[dict]) -> str:
    payload = json.dumps(rows, separators=(",", ":"))
    # {source: url}, dropping the display label -- this page only ever links
    # to a source's own project, it doesn't render SOURCE_PROJECTS' label text.
    projects = json.dumps({k: v[0] for k, v in SOURCE_PROJECTS.items()}, separators=(",", ":"))
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Review queue -- local only, never published</title>
<style>
  body {{ font: 14px/1.4 -apple-system, sans-serif; margin: 0; background: #17140f;
    color: #e7e2d8; }}
  header {{ padding: 12px 16px; background: #1f1b14; border-bottom: 1px solid #332c20;
    position: sticky; top: 0; z-index: 2; }}
  header h1 {{ font-size: 16px; margin: 0 0 6px; }}
  .warn {{ color: #e58aa8; font-size: 12px; }}
  .bar {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }}
  .bar input, .bar select {{ background: #17140f; color: #e7e2d8; border: 1px solid #443c2c;
    border-radius: 4px; padding: 5px 8px; font-size: 13px; }}
  .bar input[type=search] {{ flex: 1; min-width: 200px; }}
  .count {{ font-size: 12px; color: #a89e88; margin-top: 6px; }}
  main {{ display: flex; height: calc(100vh - 110px); }}
  .list {{ width: 40%; overflow-y: auto; border-right: 1px solid #332c20; }}
  .row {{ padding: 10px 14px; border-bottom: 1px solid #241f17; cursor: pointer; }}
  .row:hover {{ background: #221d15; }}
  .row.selected {{ background: #2a2318; border-left: 3px solid #e5a83a; }}
  .row .names {{ font-weight: 600; }}
  .row .meta {{ font-size: 12px; color: #a89e88; }}
  .decided {{ opacity: .4; }}
  .detail {{ flex: 1; overflow-y: auto; padding: 20px; }}
  .detail h2 {{ margin-top: 0; font-size: 18px; }}
  .side {{ background: #1f1b14; border: 1px solid #332c20; border-radius: 6px;
    padding: 12px; margin-bottom: 10px; }}
  .side .src {{ font-size: 12px; color: #a89e88; }}
  .reason {{ font-style: italic; color: #cfc7b4; margin: 12px 0; }}
  .actions button {{ font-size: 14px; padding: 8px 16px; margin-right: 8px;
    border-radius: 6px; border: 1px solid #443c2c; background: #241f17;
    color: #e7e2d8; cursor: pointer; }}
  .actions button.same {{ border-color: #4a8a5c; }}
  .actions button.diff {{ border-color: #b3486b; }}
  .actions button:hover {{ filter: brightness(1.2); }}
  .export {{ margin-left: auto; }}
  a {{ color: #e5a83a; }}
</style>
</head>
<body>
<header>
  <h1>Review queue &mdash; local only, never published</h1>
  <div class="warn">This page is gitignored on purpose: it holds the full unreviewed
    candidate list. Never commit pipeline/.</div>
  <div class="bar">
    <input type="search" id="q" placeholder="Search either name&hellip;">
    <select id="kind"><option value="">Any match kind</option>
      <option value="identical_key">identical_key (fast)</option>
      <option value="fuzzy">fuzzy</option></select>
    <select id="types"><option value="">Any entity types</option>
      <option value="individual|individual">individual &times; individual</option>
      <option value="organization|organization">organization &times; organization</option>
      <option value="mixed">mixed</option></select>
    <select id="sources"><option value="">Any source pair</option></select>
    <button class="export" id="exportBtn">Export decisions</button>
  </div>
  <div class="count" id="count"></div>
</header>
<main>
  <div class="list" id="list"></div>
  <div class="detail" id="detail"><p>Select a pair.</p></div>
</main>
<script>
const ROWS = {payload};
const PROJECTS = {projects};
const decided = JSON.parse(localStorage.getItem('reviewDecisions') || '{{}}');
let filtered = ROWS;
let selected = null;

function keyOf(r) {{ return r.left_key + '\\u0000' + r.right_key; }}
function typeCombo(r) {{
  if (r.left_type === 'individual' && r.right_type === 'individual') return 'individual|individual';
  if (r.left_type === 'organization' && r.right_type === 'organization') return 'organization|organization';
  return 'mixed';
}}
function money(n) {{ return '$' + Number(n).toLocaleString(undefined, {{maximumFractionDigits: 0}}); }}
function esc(s) {{ return String(s ?? '').replace(/[&<>"]/g, c => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}}[c])); }}

const sourcePairs = [...new Set(ROWS.map(r => r.left_source + ' / ' + r.right_source))].sort();
const sourcesSel = document.getElementById('sources');
sourcePairs.forEach(p => {{
  const opt = document.createElement('option');
  opt.value = p; opt.textContent = p;
  sourcesSel.appendChild(opt);
}});

function applyFilters() {{
  const q = document.getElementById('q').value.trim().toUpperCase();
  const kind = document.getElementById('kind').value;
  const types = document.getElementById('types').value;
  const sources = sourcesSel.value;
  filtered = ROWS.filter(r => {{
    if (kind && r.match_kind !== kind) return false;
    if (types && typeCombo(r) !== types) return false;
    if (sources && (r.left_source + ' / ' + r.right_source) !== sources) return false;
    if (q && !r.left_key.toUpperCase().includes(q) && !r.right_key.toUpperCase().includes(q)
        && !r.vendor_names.toUpperCase().includes(q) && !r.contributor_names.toUpperCase().includes(q)) return false;
    return true;
  }});
  renderList();
}}

function renderList() {{
  const list = document.getElementById('list');
  list.innerHTML = filtered.map((r, i) => {{
    const isDecided = decided[keyOf(r)];
    return '<div class="row' + (isDecided ? ' decided' : '') + '" data-i="' + i + '">' +
      '<div class="names">' + esc(r.vendor_names) + ' &harr; ' + esc(r.contributor_names) + '</div>' +
      '<div class="meta">' + r.left_source + ' / ' + r.right_source + ' &middot; ' +
      r.match_kind + ' &middot; score ' + r.score.toFixed(2) +
      (isDecided ? ' &middot; <b>' + isDecided.decision + '</b>' : '') + '</div></div>';
  }}).join('');
  document.getElementById('count').textContent =
    filtered.length.toLocaleString() + ' of ' + ROWS.length.toLocaleString() +
    ' shown · ' + Object.keys(decided).length.toLocaleString() + ' decided this session';
  [...list.children].forEach(el => el.addEventListener('click', () => selectRow(Number(el.dataset.i))));
}}

function renderDetail() {{
  const r = filtered[selected];
  const detail = document.getElementById('detail');
  if (!r) {{ detail.innerHTML = '<p>Select a pair.</p>'; return; }}
  const side = (names, source, cities, records, total) =>
    '<div class="side"><div>' + esc(names) + '</div>' +
    '<div class="src">' + source + (PROJECTS[source] ? ' &middot; <a href="' + PROJECTS[source] +
    '" target="_blank" rel="noopener">source project</a>' : '') + '</div>' +
    (cities ? '<div class="src">city: ' + esc(cities) + '</div>' : '') +
    (records ? '<div class="src">' + records + ' records, ' + money(total) + '</div>' : '') +
    '</div>';
  const existing = decided[keyOf(r)];
  detail.innerHTML =
    '<h2>' + r.match_kind + ' &middot; score ' + r.score.toFixed(2) + '</h2>' +
    side(r.vendor_names, r.left_source, r.left_cities, r.contract_records || r.contribution_records, r.contract_total || r.contribution_total) +
    side(r.contributor_names, r.right_source, r.right_cities, r.contribution_records, r.contribution_total) +
    '<div class="reason">' + esc(r.reason) + '</div>' +
    (existing ? '<p><b>Decided this session: ' + existing.decision + '</b></p>' : '') +
    '<div class="actions">' +
    '<button class="same" id="btnSame">Same entity</button>' +
    '<button class="diff" id="btnDiff">Different entities</button>' +
    '<button id="btnSkip">Skip</button>' +
    '</div>';
  document.getElementById('btnSame').addEventListener('click', () => decide(r, 'same'));
  document.getElementById('btnDiff').addEventListener('click', () => decide(r, 'different'));
  document.getElementById('btnSkip').addEventListener('click', () => advance());
}}

function selectRow(i) {{
  selected = i;
  [...document.getElementById('list').children].forEach((el, idx) =>
    el.classList.toggle('selected', idx === i));
  renderDetail();
}}

function decide(r, decision) {{
  decided[keyOf(r)] = {{decision, note: ''}};
  localStorage.setItem('reviewDecisions', JSON.stringify(decided));
  renderList();
  advance();
}}

function advance() {{
  if (selected === null) return;
  const next = selected + 1 < filtered.length ? selected + 1 : null;
  if (next === null) {{ selected = null; renderDetail(); return; }}
  selectRow(next);
  document.getElementById('list').children[next]?.scrollIntoView({{block: 'nearest'}});
}}

document.getElementById('q').addEventListener('input', applyFilters);
document.getElementById('kind').addEventListener('change', applyFilters);
document.getElementById('types').addEventListener('change', applyFilters);
sourcesSel.addEventListener('change', applyFilters);

document.getElementById('exportBtn').addEventListener('click', () => {{
  const rows = [['left_key', 'right_key', 'decision', 'note']];
  Object.entries(decided).forEach(([key, d]) => {{
    const [left_key, right_key] = key.split('\\u0000');
    rows.push([left_key, right_key, d.decision, d.note || '']);
  }});
  const csv = rows.map(r => r.map(v => {{
    const s = String(v);
    return /["\\n,]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s;
  }}).join(',')).join('\\r\\n');
  const blob = new Blob([csv], {{type: 'text/csv;charset=utf-8;'}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = 'review-decisions.csv';
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
}});

applyFilters();
</script>
</body>
</html>
"""


def build_review_html(queue_path: Path = None, out_path: Path = None) -> int:
    out_path = out_path or OUT_PATH
    rows = load_queue(queue_path)
    html = render(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return len(rows)


def main() -> int:
    count = build_review_html()
    print(f"  {'review queue rows embedded':28} {count:>12,}")
    print(f"  -> {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
