# Nebraska Public Records Hub — implementation plan

> The original one-page brief this plan was built from is preserved at the bottom under "Original brief".



## Context

`ne-connect/PLAN.md` describes the goal: one search box for Nebraska journalists across state contracts, campaign finance, lobbying, business filings and more, each source scraped by its own polite, deduplicating scraper, every hit linked to the primary record. Three sources are live today (contracts, NADC 2022+, lobbying positions) and the hub at `/ne-connect/` joins them at build time.

Exploration found the hub shipping in a degraded state and the lobbying collection stalled silently. This plan repairs that first, then adds three sources in the agreed order, automating each source's refresh as it lands.

**Decisions made (do not revisit):**
- Phase 0 hygiene before new sources.
- Federation stays: each source is a sibling project publishing CSVs; the hub is a read-only join; dedup lives in each scraper.
- New sources in order: NADC pre-2022 + C-1 → Secretary of State (free per-entity lookups only) → FEC. Salary roster, 990s, votes are later.
- CI modeled on `.github/workflows/ne-contracts-daily.yml`, landed per phase, not at the end.
- Lobbying backfill covers all six missing legislatures.
- C-1: if only PDFs exist, parse them (reuse the ne-contracts text pipeline).
- ne-campaign-finance gets a minimal searchable page with `?q=` so campaign-finance hits link to hosted rows.
  **Partially revisited 2026-09-15** at the project owner's explicit request: ne-connect should be "the main site," showing itemized records inline rather than a summary + link-out. For campaign finance, ne-connect's entity detail view now fetches `../ne-campaign-finance/d/rows.json` (that page's own already-published payload, not a duplicate) and renders the matching transaction rows inline, still linking to `?q=` as the fallback and the place to see everything else about that page. See `docs/SCHEMA.md`'s "Cross-fetch" section. Contracts, lobbying, disclosures and FEC individual contributions are NOT done yet -- see the note after this list.
- `ne-connect/new/`: fold `docs/*.md` and `CLAUDE.md` into `ne-connect/`, delete the rest.

**Open work: itemized records (added 2026-09-15, lobbying done
2026-09-15, disclosures done 2026-09-15, contracts done 2026-09-15, FEC
done 2026-09-16).** All five sources are done now (this section and below):
- **FEC** individual contributions: `indiv24.zip`/`indiv26.zip` pulled
  2026-09-16, self-published as `d/fec_rows.json` (`build/export_fec.py` --
  there's no `ne-fec` site to cross-fetch from) and wired into the dossier
  panel the same way contracts/campaign-finance itemized rows are. See
  Phase 3 below for the full writeup.

**Lobbying, done 2026-09-15.** `ne-lobbying/scripts/build_site.py` gained
`build_positions_index()` -> `d/positions.json`, `{principal_id: [[legislature,
bill, position, lobbyist, registration_id], ...]}`, deduped the same way
`load_lobbying_principals()` already does. ne-connect's `build_entities()`
and `widen()` both now carry `lobby_id` on the entity object (the join key,
no alias-guessing needed unlike campaign finance); the JS fetches
`../ne-lobbying/d/positions.json` lazily on first expand and renders a
"Registered lobbying positions" table (legislature, bill, position colored
support/oppose/neutral, lobbyist). Verified live against the real data:
Nebraska Cattlemen, Inc. (2,435 positions) rendered correctly alongside its
itemized campaign-finance table in the same expanded row. 39 tests passing
in `ne-lobbying` (5 new), 115 in `ne-connect` (2 new).

**Campaign-finance filers and spending, done 2026-09-15** (project owner's
follow-up: "I am also interested in campaign spending"). Committees and
candidates ("filers") are now first-class hub entities -- previously they
only appeared as the "To" column inside a contributor's transaction list.
`ingest/sources.py` gained `load_campaign_filers()`/
`load_legacy_campaign_filers()` (era-keyed like `load_contributors()`,
`role="filer"`, always `entity_type="organization"`) and
`load_spend_only_filers()` (a filer with real spending but zero itemized
receipts -- everything it raised was sub-threshold -- still needs an
entity or its spending is unreachable). Every filer dict key carries a
`"filer:"` prefix so merging with the contributor dict
(`{**load_contributors(), **load_campaign_filers(), ...}`) can never
silently clobber a name that happens to be both. `ne-campaign-finance`
gained the spending-side counterpart to `d/rows.json`:
`build_expenditures_index()` -> `d/expenditures.json`, keyed by filer name,
reading `expenditures.csv` + `expenditures_legacy.csv` (never
`independent_expenditures.csv` -- a documented subset, not extra rows).
ne-connect fetches it lazily and renders a "Campaign spending" table,
included in the per-entity CSV export too. Verified live against the real
data: Jim Pillen for Governor ($24.4M modern + $841,574 pre-2022 raised,
1,133 itemized expenditures -- payroll, campaign staff, a Zoom
subscription, bank fees) rendered correctly. Also fixed two real bugs
found while building this: a `figures()` guard against a spend-only
filer's truthy-but-zero totals rendering a misleading "$0 · 0 records"
line, and a CSV/formula-injection hole in `csvCell()` (a state-published
description or payee name starting with `=`/`+`/`-`/`@`/tab/CR could open
as a live formula in Excel) caught by an automated security review of the
CSV-download commit and fixed the same day. 120 tests passing in
`ne-connect` (5 new), 121 in `ne-campaign-finance` (3 new).

**Two more fixes shipped the same day, both from direct feedback on the
CSV/itemized-table work above**: the download button moved above the
itemized tables (it was getting lost below a 200-row inline dump), and all
four itemized sections (contributions, spending, positions, and now
disclosure items below) render through a shared scrollable, searchable
`itemizedBlock()` instead of a flat page-length table. A real bug was
caught wiring the filter box: any click inside an itemized table bubbled
up and collapsed the entity it lived in; fixed with an early return on
clicks inside `.txns-slot`.

**Disclosures, done 2026-09-15** (project owner: "start on disclosures
next"). C-1/C-2 financial-interest items are the third source to get this
treatment, and the simplest join yet: unlike campaign finance's
alias-guessing, `disclosure_id` is the state's own filing id, already the
exact `source_id` `load_disclosure_filers()` keys its `Party` objects by --
no guessing needed. `ne-campaign-finance/scripts/build_site.py` gained
`build_disclosure_items_index()` -> `d/disclosure_items.json`, keyed by
`disclosure_id`, reading `financial_interests.csv` +
`financial_interests_legacy.csv` (the legacy file doesn't exist on this
machine yet -- handled gracefully, same as every other optional legacy
file). Because one person can file more than one disclosure,
`build_full_index()`/`build_entities()` in `ne-connect` expose a
**`disclosure_ids` list** (not a single id like `lobby_id`). Verified live
against the real data: Rex A Adams (42 disclosed items) rendered
correctly, including several rows that are visibly OCR-garbled form
instructions rather than real answers ("Type have nothing to report,
write NONE") -- exactly the known data-quality issue
`load_disclosure_filers()`'s docstring already flagged, now visible to a
reader with the caveat rendered directly beneath the table rather than
buried in documentation. 124 tests passing in `ne-campaign-finance` (3
new); `ne-connect`'s own test count is unchanged (the disclosure-items
render/fetch logic is JS, not covered by its Python suite, same as every
other itemized table).

**Contracts, done 2026-09-15** (project owner: "The contract database is
live at ne-contracts"). The fourth and hardest of the four: `ne-contracts`
already runs a large, tightly-verified real search build
(`scripts/build_site.py`, a bespoke binary index with its own selftest
machinery) that this deliberately never touches. A new, fully independent
`ne-contracts/scripts/export_vendor_rows.py` reads `nu_contracts.csv` +
`nu_purchase_orders.csv` directly, same "thin adapter" pattern as the other
three sources.

**A real, hard technical constraint surfaced building this, not just a
design choice**: a single combined export came to ~190 MB (one vendor,
Amazon Capital Services, accounts for ~25 MB of it across ~66,900
purchase-order line items) -- past GitHub's hard 100 MB per-file push
limit, discovered by actually building the file and hitting the wall.
Fixed by sharding `d/rows/<A-Z|_>.json` by the vendor name's first
character (27 shards, largest ~42 MB) rather than truncating any real
record; ne-connect's JS mirrors the same shard key and fetches only the
shard(s) a vendor's name and aliases fall into, caching each shard
individually. Verified live against real data: Hawkins Construction
Company's 81 contracts/purchase-orders rendered correctly (agency, amount,
dates, status, linked to the real `statecontracts.nebraska.gov` document),
alongside its lobbying positions in the same expanded row, and the
per-entity CSV export includes contract rows with the real detail URL.

**A second real constraint, found reading `ne-contracts`'s own history
before touching it**: this repo does not commit its `d/` payload at
all -- a comment in `.github/workflows/pages.yml` explains it once did,
until a 50 MB payload's retired build directories bloated `.git` to
546 MB, and the fix was building at deploy time and publishing the
artifact without ever committing it. Committing a 190 MB sharded export
would have reintroduced exactly that problem at a larger scale. Instead,
`pages.yml` gained one new step, "Export vendor rows for ne-connect",
placed after the existing "Keep only the build just made" cleanup (so a
`d/rows/` entry isn't swept away as an unrecognized build directory) and
before "Save the payload for the next run" (so it rides along in the
same cache entry `build_site.py`'s own payload already uses). `d/rows/`
is gitignored, matching every other build output in this repo -- nothing
new committed, same as before this change.

183 tests passing in `ne-contracts` (175 pre-existing, confirmed still
green, plus 8 new); `ne-connect`'s own test count is unchanged (same
JS-only reasoning as the other three itemized tables).

**Verified state driving Phase 0** (paths under repo root):
- Position sweep died on an uncaught `requests.ReadTimeout` after legislature 109. `ne-lobbying/scripts/lobby.py:161-178` retries only HTTP 429; `:436-441` catches only `KeyboardInterrupt`/`RateLimited`. `sweep_all.sh:19-22` treats a vanished pid as "finished", so 108-3, 108, 107-1, 107, 106, 105 were never started. 39,909 positions for 109 only.
- `expenses.py:170-182 scrape_aggregate` appends through `write_rows` (`:158-167`) with no guard; `sweep_all.sh:36` reruns it each chain → `expenses_statewide.csv` has 816 rows, 408 expected.
- Form B per-entity sweep running now (pid 38545, 1,400 of 5,412 entity-years). Form C (8,604 entity-years → `expenses_principal.csv`, already read by `ne-connect/ingest/sources.py:158-186`) follows. Do not restart the chain while it runs.
- Lobbying CSVs are gitignored and exist only on this machine.
- Hub `d/entities.json` (78,968 entities, 3.1 MB) has no aliases or URLs; `build_site.py:538-548 widen()` sets `aliases: []`, so typed searches lose alias matching and all primary-record links. `lite: true` is never read.
- Campaign-finance entities have no `source_url` (`build_entities.py:205-208`).
- `data/manual/resolutions.csv`: zero human decisions; 2,134 pairs queued.
- `ne-connect/README.md` header stale (779 entities / 86 tests vs 78,968 / 91); `:278-281` falsely says CI builds the payload.
- Root `index.html:942-949` and `sitemap.xml` link only ne-contracts. `pages.yml`'s blanket rsync also publishes `ne-connect/new/site/index.html`, a skeleton page.
- `ne-contracts/index.html:2417` reads `?q=` on landing, so a deep link into a vendor search works today.
- `git count-objects`: 561 MiB loose objects vs 4 MiB packed.

## Dedup contract (the one requirement PLAN.md states explicitly)

Every scraper must be idempotent: rerunning never adds a row it already has. Each source owns a natural key and a write mode.

| Source | Natural key | Write mode | Where enforced |
|---|---|---|---|
| Contracts | full `Detail URL` hash | append, known keys skipped | `ne-contracts/scripts/scrape.py:694,806,1041` (done) |
| NADC modern | `receipt_id` + `include_in_total` | rewrite from newest snapshot | `ne-campaign-finance/scripts/normalize.py:226,257` (done) |
| NADC legacy | `(source_form, natural key from rtf)` | rewrite from frozen zip | Phase 1 |
| Lobbying positions | bill token in `scrape_progress.json`; row grain is `registration_id` | append per bill, bill-level skip | `lobby.py:402-420` (done) |
| Lobbying expenses, per entity | `form/entity_id/year` token | append per token | `expenses.py:198-216` (done) |
| Lobbying expenses, statewide | `(form, year, category)` | **rewrite** | Phase 0.3 (bug today) |
| C-1 | `disclosure_id` (document URL) | rewrite from raw captures | Phase 1 |
| SoS | `query_key` token; row key `sos_account_number` | rewrite from cache | Phase 2 |
| FEC | `sub_id`; fallback `(cycle, image_num, tran_id)` | rewrite from raw zip | Phase 3 |
| Hub | entity key + source + era | full rebuild | `build_entities.py` (done) |

A shared check script in each project (`scripts/check_data.py`) asserts key uniqueness on its outputs and runs before `build_site.py` and in CI.

---

## Phase 0 — Repair and harden

Split in two: **0A** can be done now while the Form B sweep runs; **0B** waits on the sweeps. Unattended scrape time: Form B remainder ~3 h, Form C ~7 h, six legislatures ~7,500 requests ~8 h. Roughly 18 h total, run over a weekend.

### 0A — while the sweep runs

**0.1 Transient network errors get the RateLimited treatment** — done.
- `lobby.py`: add `class Unreachable(RateLimited)` beside `RateLimited` (`:112`). Every existing `except RateLimited` (`lobby.py:438`, `:492`, `expenses.py:225`) then inherits stop-cleanly-save-resume.
- `Fetcher._fetch` (`:161-178`): wrap `session.get/post` in `try/except (requests.ConnectionError, requests.Timeout)`; back off `delay * 2**(attempt+1)`, count in `network_retries`, continue; after `MAX_RETRIES` raise `Unreachable`.
- Tests (`ne-lobbying/tests/test_lobby.py`): stub session raises twice then succeeds → page returned, `network_retries == 2`; always raises → `Unreachable`, is-a `RateLimited`.

**0.2 Completion marker and exit codes** — done. (`sweep_all.sh`'s exit-code handling was found overnight to only halt the chain on 130, letting a crashed stage silently continue as if complete — see `ne-lobbying` commit `3bb62a8`: `stop_if_interrupted()` now flags any non-zero, non-interrupt exit too.)
- `scrape_positions` (`:377-456`): `finished=True` only when the loop exits normally; `finally` writes `progress["complete"]` and `progress["legislatures_requested"]`. `main()` (`:507-540`) returns 0 if complete, 2 otherwise. Same in `expenses.py scrape_entities` (`:185-234`) with `progress["complete"] = {"B":…, "C":…}`.
- `sweep_all.sh`: replace the pid-wait (`:19-26`) with a bounded retry loop (≤12 attempts, `sleep 300`) that reruns `lobby.py --all --prefixes LB LR --delay 2.0` until `complete` is true; same loop around `--entities` (`:44`). Keep `set -u`; no `set -e`.
- Test: sibling of `test_progress_round_trips` (`test_lobby.py:130`) for `complete` false after a simulated `RateLimited`, true after a clean `--max-number 2`.

**0.3 Idempotent statewide totals** — done.
- `write_rows`: add `mode` (default `"a"`); `scrape_aggregate` passes `"w"`. One-time repair: rerun `--aggregate` (all 24 responses cached → zero requests); verify 408 rows.
- New `ne-lobbying/scripts/check_data.py` fails on duplicate keys in any expenses CSV; chain runs it before `build_site.py`.
- Test: `scrape_aggregate` twice against a stub fetcher → one pass's row count.

**0.6 Hub lazy index keeps aliases and links, header-driven**
- Contract `Detail URL`s are opaque ~286-char strings; a URL column for ~54k vendors is ~15 MB. Ship link *tokens* and derive URLs in the page.
- Change `d/entities.json` from bare positional arrays to `{"columns": [...], "rows": [[...], ...]}` so every later phase adds a named column without touching the JS slot logic. Initial columns: `name, bits, contract_amt, contract_recs, contrib_amt, contrib_recs, lobby_recs, lobby_id, aliases` (`aliases` only for the ~3,227 entities with >1 alias; `lobby_id` for ~650). Expected growth ~350 KB; keep under 4 MB raw.
- `build_full_index` (`build_site.py:181-214`) emits the header; `widen()` (`:538-548`) reads by column name and derives links from templates defined once: contracts → `../ne-contracts/?q=<name>`; lobbying → `https://nebraskalegislature.gov/lobbyist/view.php?link=view_principal&id=<lobby_id>` (same as `sources.py:230-233`); campaign finance → `../ne-campaign-finance/?q=<name>` (Phase 1 builds the page; until then the NADC search page from 0.7).
- Read the `lite` flag: "single source; linking to that source's search for this name" instead of the unconditional "nothing was matched to it".
- Tests: header present; row length equals column count; one-alias entity has empty alias cell; lobbying entity carries its id.

**0.7 Stopgap door to NADC for campaign-finance entities**
- `sources.py load_contributors` (`:90-127`): set `sample_url` to the FirstTuesday contributions search page (`ne-campaign-finance/README.md:111`), labelled "search NADC for this name". Replaced by the hosted page in Phase 1.

**0.11 Root site links**
- `index.html:942-949`: project card for the hub, plus cards for campaign finance and lobbying. `sitemap.xml`: add the three paths.

**0.12 Fold `new/` into `ne-connect/`, delete the rest**
- Move `new/docs/{DATA_SOURCES,ENTITY_RESOLUTION,PRIVACY,SCHEMA,UI_SPEC}.md` → `ne-connect/docs/`; `new/CLAUDE.md` → `ne-connect/CLAUDE.md`. Absorb `ne-connect/PLAN.md` (untracked) into a "Goals" section at the top of `docs/DATA_SOURCES.md` and delete it.
- Reconcile while moving: `SCHEMA.md` describes the real artifacts (`canonical_entities.csv` columns `build_entities.py:190-212`, ledger `resolutions.py:38-48`, the entities.json header layout, this plan's dedup table); `ENTITY_RESOLUTION.md` carries the live formula (`match.py:98-100`, `AUTO_WEIGHT_MULTIPLE`, persons never auto); `DATA_SOURCES.md` marks the three live sources shipped and adds FEC; `CLAUDE.md` architecture block matches `build/`, `ingest/`, `resolve/`, root `index.html`; drop DuckDB/parquet/cents.
- Delete `new/` wholesale. This also stops `pages.yml` publishing `new/site/index.html`. Commit message notes `scrapers/base.py`'s manifest idea is carried into Phase 2.

**0.13 Optional local `git gc`**
- `git gc` or `git repack -a -d -f --window=250`. Local only.

### 0B — after the sweeps

**0.4 Form C reaches the hub** — done. Verified against the real `expenses_principal.csv`
(22,289 rows): every "11." row reads exactly `"11. Total (Sum of 2, 3d, 4, 5, 6, 7, 8, 9d,
and 10d)"`, matching `sources.py`'s prefix check and the test fixture. No fix needed.

**0.5 Lobbying backup: GitHub Release, not commits** — done. [`lobbying-data-2026-09-14`](https://github.com/diepjustin/ne-lobbying/releases/tag/lobbying-data-2026-09-14): all `data/*.csv` + both progress JSONs, gzipped, 2.8 MB total (25 MB uncompressed). Backup only — not yet consumed by any workflow; `.github/workflows/ne-lobbying-daily.yml` (0.14) is the first consumer, per the `pages.yml` pattern.

**0.8 Bounded review-queue slice (~2 h)**
- Decide the 158 `identical_key` pairs plus the top 50 fuzzy pairs by dollars with `build/review.py --same/--different --by jdiep --note`. Optional `--next N --kind identical_key` helper; write path unchanged. Defer the remaining ~1,900.

**0.9 Rebuild and commit** — done (`4781e1a`). `resolutions.csv` unchanged (still empty; no human decisions yet, see 0.8).

**0.10 READMEs with real numbers** — done.
- `ne-connect/README.md`: header from `entities_summary.json`; rewrite `:278-281`; document the header-driven index; link `docs/`.
- `ne-lobbying/README.md`: actual positions / tests / legislature coverage / Form B and C status; describe the release backup.

**0.14 First two workflows (pattern in Automation notes below)** — done. Both
verified green on `workflow_dispatch`: [`ne-campaign-finance` run](https://github.com/diepjustin/ne-campaign-finance/actions/runs/34889845303)
(29s), [`ne-lobbying` run](https://github.com/diepjustin/ne-lobbying/actions/runs/34889922350)
(1m18s, including the release-fallback restore path on the expected first-run
cache miss). `--refresh-legislature` (`lobby.py`) shipped for the weekly step.
- `ne-campaign-finance-daily.yml`: tests → restore cache (miss just redownloads) → `download_extracts.py` → `validate.py` shrink guard → `normalize.py` → save.
- `ne-lobbying-daily.yml`: nightly → restore `ne-lobbying-data-` with `lobbying-data-*` release fallback → `--aggregate` → `--entities` current year `--refresh` → `check_data.py` → save. Weekly (Sundays): `lobby.py --legislatures 109 --refresh-legislature`. Monthly (1st): backup release. Historical legislatures never re-swept in CI. Weekly/monthly steps correctly no-op'd on this (Monday) test run.

### Phase 0 verification
- `ne-lobbying`: `pytest tests -q`; 408 unique statewide rows; kill a `--max-number 3` run, confirm `complete:false`, rerun continues; `check_data.py` clean.
- `ne-connect`: `pytest tests -q`; summary totals unchanged except human decisions; locally type a truncated lobbying alias and confirm match + link; type a vendor and confirm the contracts link lands filtered.
- Root: `python3 -m http.server`, click through the new cards. Both workflows green on `workflow_dispatch`.

Effort: 5-7 working days plus ~18 h unattended sweeps.

---

## Phase 1 — NADC pre-2022 + C-1, and a searchable campaign-finance page

Lives in `ne-campaign-finance/`.

**1.1 `scripts/download_legacy.py`** — done 2026-09-12.
- Fetches `nebraska.gov/nadc_data/nadc_data.zip` once into `data/raw/legacy/<date>/`, extracting only the 13 forms 1.2/1.5 need (not all 64 — see the script's docstring for the list and why); sha256 into `scrape_meta.json["legacy"]`; reruns compare sha and skip, a changed sha warns loudly and captures fresh rather than overwriting. Reuses `fetch_zip`/`DEFAULT_USER_AGENT` from `download_extracts.py`.
- `scripts/validate_legacy.py`: header gate like `validate.py`, headers transcribed from a real pull. Exact-duplicate rows counted, not fatal (198-574 seen in the biggest forms — expected for paper records re-entered by hand). **New finding while building this**: six of the thirteen forms (formb2a, formb4a, formb72, formb73, formb2b, formb4b1) have every row one field short of the header — "Report ID" is essentially never populated and the export drops it rather than emitting an empty field, confirmed by direct byte inspection. Also counted, not fatal, but `normalize_legacy.py` (1.2) needs to read these six positionally rather than with a strict `dict(zip(header, row))`.
- Ran end-to-end against the live zip: all 13 forms extract and validate cleanly, rerun correctly skips on unchanged sha256. 57 tests (14 new, `ne-campaign-finance`).
- Date columns carry sentinel values (`12/31/9999`, `01/01/0001`, `01/01/0900` all seen) — not yet enforced as a validator warning; worth adding when 1.2 starts parsing dates.

**1.2 `scripts/normalize_legacy.py` → `contributions_legacy.csv`, `loans_legacy.csv`,
`other_receipts_legacy.csv`, `expenditures_legacy.csv`** — done
(`ne-campaign-finance@2a8f910`). Real numbers: 253,552 contributions, 110 loans,
1,205 other receipts, 125,809 expenditures. The three decisions below were made
by the project owner on 2026-09-14 (all three recommended options), not guessed:
formb73 `E` → `expenditures_legacy.csv`; formb5 `L` → new `loans_legacy.csv`;
formb4b1 `A`/`B` → kept in `expenditures_legacy.csv`, flagged unclassified.
Also found and fixed while building this: six forms are missing "Report ID"
specifically (the second-to-last column, not the last as the recon below loosely
described) — right-padding as that description implies would have silently
swapped Contributor Name into Report ID's slot; fixed by dropping "Report ID"
from the header before parsing, confirmed against real extracted lines from all
six forms. Sentinel dates (`12/31/9999` etc.) are now dropped and counted rather
than parsed into real-but-absurd dates. 15 new tests, 76 total in
`ne-campaign-finance`.
- **Per-row classification recon done 2026-09-12.** Read `nadc_tables.rtf`'s actual field descriptions (not just the header text) for all nine contribution/expenditure forms. Three findings that change how naive "this form = contributions" / "that form = expenditures" mapping would misclassify real dollars:
  1. **formb73 mixes contributions and the filer's own spending in one table.** Its `Nature of Contribution` column takes `I`=In-Kind, `P`=Personal Service, or **`E`=Independent Expenditure** — an `E` row is the corporation/PAC's own spending, not money it received, and belongs in `expenditures_legacy.csv`, not `contributions_legacy.csv`. Counted on the real file: **635 of 7,328 rows (8.7%) are `E`** — not a rounding error, would meaningfully inflate a "money this PAC received" total if left in. (Real distribution: `I` 6,470, `E` 635, `P` 203, blank 20.)
  2. **formb5's `Nature of Contribution` includes `L`=Loan** alongside `M`=Money, `I`=In-kind, `P`=Pledge. `normalize.py`'s existing rule for the modern data — a loan is borrowed money, not support, and gets its own `loans.csv` rather than inflating `contributions.csv` — applies here too. Counted: **110 of 4,712 rows (2.3%) are `L`**. (Real distribution: `M` 4,266, `I` 247, `L` 110, blank 65, `P` 24.) Decide whether legacy loans get a `loans_legacy.csv` (matching modern) or are simply excluded with a count logged; either is defensible, silently including them as contributions is not.
  3. **formb1ab/formb2a/formb4a's "Unpaid Pledges" column is a promise, not money**, same as the modern pipeline's "a bare Pledge is deliberately NOT a contribution" rule (`normalize.py`'s module docstring, trap #1). These forms report Cash/In-Kind/Unpaid Pledges as three separate amount columns per row — one legacy row can fan out into up to two canonical contribution rows (cash, in-kind) plus a non-contribution pledge record, not one row each.
  - Less urgent, worth a comment rather than a blocker: **formb4b1's `Nature of Expenditure` is mostly clean but not entirely** — counted: `D` 37,946, `E` 4,170, `I` 3,204, and then **346 `A` and 51 `B`, values not in the schema doc's documented set (`D`/`I`/`L`/`E`) at all**, plus 2 `L` (Loan). Handle the way `normalize.py` already handles an unrecognized transaction type elsewhere: keep the row, report the unknown code, don't silently drop or misclassify it.
  - Forms confirmed clean (their type/nature field values are all straightforwardly contribution- or expenditure-only, per the same schema read): formb72 (Direct contributions, Amount only, no nature field), formb2b (`D`=Direct/`K`=In-kind/`I`=Independent Expenditure — all genuinely expenditures since this is the *committee's own* Form B-2 expenditure schedule, unlike formb73's corporate-filer ambiguity), formb1d (plain expenditures, no nature field).

**1.3 Searchable page `ne-campaign-finance/index.html` with `?q=`** — done
(`ne-campaign-finance@91417a2`, `ne-connect@dc78f89`). 25,173 contributors and
926 filers inline (keyed by raw name, not `org_id` — a name-based key matches
this project's convention elsewhere); `d/rows.json` lazy per-contributor
transaction payload (117k modern rows, era not yet tagged — 1.2 hasn't landed).
`OrganizationDetail.aspx` verified live: the real path is
`/PublicSite/SearchPages/OrganizationDetail.aspx?OrganizationID=<org_id>`, not
`/PublicSite/OrganizationDetail.aspx` as a plausible guess would have it.
`docs/PRIVACY.md` respected: address_1/address_2 never reach the JSON payload
(tested), individuals render as a plain transaction list with no aggregate
stat card, no reverse-address search or bulk export built. Hub's
`campaign_finance` link template switched to `../ne-campaign-finance/?q=`.
Verified live in-browser: search, filer/contributor expansion, individual vs.
organization presentation, `?q=` deep-linking. 61 tests in
`ne-campaign-finance` (4 new), 99 in `ne-connect`.

**1.4 Hub ingest with `era`** — done. `Party.era` (default `"modern"`);
`load_contributors()` keys its dict by `(name, era)` so the same donor in both
eras never clobbers itself; `load_legacy_contributors()` wraps it for
`contributions_legacy.csv`. `build_entities.py` merges both eras before
keying; `era` column lands in `canonical_entities.csv`. `build_site.py`: inline
entities carry `contrib_eras` (rendered as two lines, never summed, when both
present); the lazy index gained `contrib_amt_legacy`/`contrib_recs_legacy`
columns; `retrieval_dates()` adds the frozen-data note, surfaced next to the
Contributions provenance line whenever an entity has pre-2022 money. Verified
live: 107,146 canonical entities (up from 79,351), 5,627 with both
campaign-finance eras, both the inline (Hawkins Construction Company) and
lazy-index (055 - FAST PLAZA, LLC) rendering paths checked in-browser with no
console errors. `d/entities.json` is now 5.28 MB raw / 1.37 MB gzipped — over
0.6's original 4 MB raw budget (that budget predates the legacy data almost
doubling the contributor count); gzipped size is what actually ships over the
wire and is still small, but the raw-size note in 0.6 should be revisited.
99→102 tests passing.

**1.5 C-1 / C-2 statements of financial interest, `scripts/scrape_c1.py`** — scraper,
PDF pipeline and legacy normalizer done 2026-09-15 (`ne-campaign-finance`); hub
ingestion (the "Hub:" bullet below, `d/rows.json` wiring) still open.
- **Built and verified end-to-end 2026-09-15.** `scripts/scrape_c1.py`
  (search-grid index), `scripts/build_financial_interests.py` (PDF fetch/OCR),
  `scripts/normalize_legacy_c1.py` (the four legacy forms below). Live run:
  20 filings scraped across two 2023 result pages (10 Manual, 10 Electronic);
  one Electronic filing resolved and parsed (67 items, clean text layer, no
  OCR); six Manual filings downloaded and parsed (202 items, 5 of 6 needed
  OCR). Legacy run against the real zip: 11,523 items from 81,256 formc1
  filers, 995 C-2 statements, one unrecognized `Type of Inocome` code class
  logged rather than dropped. 115 tests passing.
  - **The `__doPostBack` mystery is solved** (see `docs/DATA_SOURCES.md`'s C-1
    entry for the full writeup): it is exactly Manual (scanned, direct GUID
    link) vs Electronic (e-filed, no static URL — the state renders the PDF
    fresh into the postback response as a base64 data URI).  `document_url`
    for an Electronic row falls back to the search page itself, same
    "stopgap door" pattern as 0.7.
  - **OCR is confirmed the primary path for Manual filings** (75% of a real
    sample have no text layer), and every OCR-derived row carries `ocr: true`
    so it is never presented at the same confidence as a verbatim
    text-layer or legacy row. Electronic filings, by contrast, are clean
    born-digital PDFs needing no OCR at all.
  - **Open/approximate:** item extraction segments each filing's text by its
    `ITEM N` headers rather than doing a full field-level parse; on a
    mostly-blank filing the line-fallback path can pick up instructional
    prose as if it were a filer's answer. Worth a follow-up pass.
- **Recon done 2026-09-11 — splits this task in two, and the pre-2022 half no longer needs a scraper at all.** `nadc_data.zip` (1.1) already contains `formc1.txt` (81,804 rows, "Statement of Financial Interest" — filer name/office/address plus filing metadata), `formc1inc.txt` (10,604 rows, income sources/business associations/financial institutions/creditors/gifts, one row per item), `formc1prop.txt` (3 rows, real/other property — essentially unused), and `formc2.txt` (1,013 rows, "Potential Conflict of Interest Statement"). Full column list in `nadc_tables.rtf` / `docs/SCHEMA.md`. This is structured pipe-delimited data through the 2022-07-11 freeze date — no PDF, no OCR, normalize it the same way as every other legacy form in 1.2.
  - **Privacy:** `formc1.txt`'s `Candidate Address` is a home street address in plaintext. Strip to city/state/zip before it reaches `canonical_entities.csv` or any display — `docs/PRIVACY.md` rule 2, non-negotiable.
  - `Candidate ID` + `Date Received` is the join key across `formc1`/`formc1inc`/`formc1prop` per the schema doc's own note ("Use along with Date Received to link to FORM10").
- **2018-present C-1/C-2 recon also done 2026-09-11.** Live, no-login search page:
  `nadc-e.nebraska.gov/PublicSite/SearchPages/Search.aspx?SearchTypeCodeHook=86C705B4-76BE-4FD9-B9A0-B607711F8A3A`.
  Filing Year dropdown only goes back to 2018 — **2018 through 2022-07-11
  overlaps `nadc_data.zip`**, so `scrape_c1.py` needs to dedup against
  `formc1.txt` rather than just split cleanly on the freeze date; only ingest
  online filings dated after it, or key on filer+year and let the newer source
  win. Classic ASP.NET WebForms (`__VIEWSTATE`/`__doPostBack`, no JSON
  endpoint), paginated grid — same POST-body-cache-key shape as `lobby.py`'s
  `Fetcher`, confirming 1.5's original plan to copy it. **No "Individual
  Supplemental Filer" checkbox on this page** — that quirk may belong to a
  different search; verify before coding rather than assuming `DATA_SOURCES.md`'s
  original note applies here unchanged.
- **Every row's "View" link is a direct PDF**, not another hop:
  `../Reporting/DocumentImagePopup.aspx?PFD_FilingID=<guid>`, confirmed via
  `fetch()` — `content-type: application/pdf`, one sample 2.8 MB. Filer index
  can therefore be built from the search grid alone: copy `lobby.py:Fetcher`
  (POST body in cache key `:133-141`) → `data/processed/c1_filings.csv`
  (`disclosure_id, year, filer_name_raw, filer_office, document_url,
  retrieved_at`), with `document_url` already resolvable without a second
  scrape. Every filing gets a link even before parsing.
- PDF parsing (decided: parse, post-2022-07-11 filings only now): reuse `ne-contracts/scripts/extract_text.py`'s pypdf + pdfminer path (`:52-53`) for text-layer PDFs; for scanned ones run the OCR pilot ne-contracts scoped but never ran (`ne-contracts/README.md:1057`). **Check a handful of these PDFs for a text layer before committing to a pipeline** — the file size and the "DocumentImagePopup" name both suggest scanned images are the common case here, not the fallback, which would make OCR quality the actual bottleneck rather than a hedge. Output `financial_interests.csv` (`disclosure_id, item_type, counterparty_name_raw, detail, source_url, retrieved_at`) with the state's text verbatim, `era` column matching 1.2/1.4's convention. Raw PDFs immutable under `data/raw/c1/`.
- Hub: source `"disclosures"`, bit 32 (reserve 8 = SoS, 16 = FEC now). **Filers
  done 2026-09-15** (`entity_type="individual"` so they search but never
  auto-merge, `match.py:decide` — verified live, 2 real cross-source
  connections found: Jon Abegglen and Misty Ahmic, both disclosure filers who
  are also campaign contributors). **Counterparty orgs deliberately not
  ingested yet** — `financial_interests.csv`'s line-fallback item types
  (`real_property`, `other_financial_interest`, `gift`) can surface the C-1
  form's own instructional boilerplate as a counterparty name (a real check
  found `"personal residence need not be reported."` as a sample value);
  shipping that as an organization into `canonical_entities.csv` would be a
  real data-quality bug, not just a caveat. Revisit once item-type-aware
  ingestion (or a parser fix) exists.

Tests: `test_normalize_legacy.py` (header gate, dedupe count, era, idempotency); `test_build_site.py` for the search index shape and `?q=`; `ne-connect/tests/test_era.py`; C-1 parser tests from trimmed HTML and a fixture PDF.
**1.6 Workflow**: extend `ne-campaign-finance-daily.yml` with the legacy sha check, `scrape_c1.py --new-only`, and `build_site.py`; then `ne-connect-nightly.yml` (see Automation notes) since the hub now has two automated inputs plus contracts.
**Partial, done 2026-09-15**: legacy sha check + `normalize_legacy.py` +
`build_site.py` added to `ne-campaign-finance-daily.yml`, verified green on
`workflow_dispatch` (a real bug caught and fixed along the way — see
`ne-campaign-finance@d97d520`: `download_legacy.py`'s skip check trusted
committed metadata without confirming the extracted files actually existed
on that runner, so a fresh CI cache silently produced zero legacy data
while claiming "skipping extraction, nothing new"). `scrape_c1.py` is
**deliberately not wired into the cron** — it has no `--new-only`/
incremental mode yet, and an unbounded nightly sweep of a live financial-
disclosure site needs that logic and a cadence decision first, not a
silent overnight default. `ne-connect-nightly.yml` not started — bigger
scope (touches live Pages publishing), held for explicit sign-off.
Risks: rtf schema quality; legacy committee ids not joinable to modern; OCR quality on C-1 scans; `d/rows.json` size (measure; split by first letter if over ~5 MB).
Effort: 8-11 days (legacy 3-4, search page 2, C-1 3-5).

---

## Phase 2 — Secretary of State lookups (`ne-sos/`)

New sibling mirroring ne-lobbying: `README.md`, `requirements.txt`, `scripts/sos.py`, `scripts/check_data.py`, `data/{raw,cache}` gitignored, `data/sos_progress.json` tracked, `tests/`.

**2.0 Gate: terms of use — CHECKED 2026-09-14, BLOCKED.** Fetched `sos.nebraska.gov/robots.txt` and `www.nebraska.gov/robots.txt` directly: neither disallows the relevant paths. But the SOS page's "Corporation and Business Search" link doesn't stay on `sos.nebraska.gov` — it goes to `https://www.nebraska.gov/sos/corp/corpsearch.cgi`, a legacy Nebraska.gov/Tyler Technologies (formerly Nebraska Interactive) app. That host's site-wide "Nebraska Use Policy" (`https://www.nebraska.gov/policies/`, linked from the nebraska.gov footer) bars automated access outright: *"You may not without our prior written permission use any computer code, data mining software, 'robot,' 'bot,' 'spider,' 'scraper' or other automatic device... to monitor or copy any of the Web pages, data or content found on this Site."* Full quote and citation in `docs/DATA_SOURCES.md`'s Secretary of State entry, marked `blocked`. Per CLAUDE.md rule 6, **this phase stops here** — no `ne-sos/` repo, no `scripts/sos.py`, no scraping. Nothing below (2.1–2.4) is superseded by new information (the free search page itself, confirmed live 2026-09-14, is still a simple `Name Starts With / Keyword / Sounds Like / Exact Match / Account Number` radio-button form on `corpsearch.cgi`, not WebForms — closer to a plain GET/POST than `lobby.py`'s ASP.NET target — but that's moot since nothing gets built against it without written permission from Nebraska.gov/Tyler). Revisit only if permission is obtained; see `docs/DATA_SOURCES.md` for the contact path.

**2.1 Input.** (blocked by 2.0 — not started) `ne-connect/data/canonical_entities.csv` filtered to organizations; canonical name first, aliases only on no result. Priority: cross-source entities, lobbying principals, vendors by contract total. `--limit N` per run; never a full pass in one go (~55k names ≈ 30 h).

**2.2 `scripts/sos.py`.** Copy `Fetcher` from `lobby.py:118-180` (with 0.1), change `BASE`; add `write_manifest()` per run (`data/raw/<date>/manifest.json`: source URLs, retrieved_at, sha256). Raw HTML content-addressed, never overwritten; `--refresh` writes a new dated capture. Parse results (name, account number, type, status) and detail (registered agent, principal office, filed documents). `match_kind` = `exact` (via the hub's `normalize_org`) / `multiple` / `none`; only `exact` carries `hub_entity_id`. Outputs `sos_entities.csv` (`query_key, hub_entity_id, match_kind, sos_account_number, name_raw, entity_type, status, registered_agent_raw, principal_office_city, principal_office_state, principal_office_zip, source_url, retrieved_at`) and `sos_agents.csv`. Street addresses stay in raw only. Resumable tokens flushed every 25; CSVs rewritten from cache each run. 2 s delay, `Retry-After`, UA with contact (copy `test_user_agent.py` from ne-contracts).

**2.3 Hub: bit 8 and connections.** `load_sos_entities()` → `Party(source="sos", role="registrant", source_id=account, sample_url=detail URL)`. Join by construction: extend `resolve/authority.py short_circuit` to accept pre-declared links with `match_kind="sos_lookup"`; `multiple`/`none` never enter. Named column `sos_status`. New `build/build_connections.py` → `data/connections.csv` (`entity_a, entity_b, basis, evidence`) with `shared_registered_agent` and `same_principal_office` (normalized address, displayed as city+ZIP). Org-to-org only; never a person-to-person edge. Rendered inline for cross-source and SoS-linked entities only.

**2.4 Workflow** `ne-sos-weekly.yml`: restore hub cache for `canonical_entities.csv`, restore `ne-sos-data-`, `sos.py --limit 500`, `check_data.py`, save.

Tests: parsers from trimmed captures; `match_kind`; idempotency; hub union-without-scoring; connection rules. Risks: ToU forbids; pagination; exact-name collisions (show status and city). Effort: 4-6 days plus the gate.

---

## Phase 3 — FEC federal campaign finance (`ne-fec/`)

**Recon + scaffolding done 2026-09-15.** Terms-of-use gate cleared (see
`docs/DATA_SOURCES.md` for the exact robots.txt/legal-notice finding).
`download_bulk.py`, `filter_ne.py`, `normalize.py`, `check_data.py` built and
validated against the real 2024-cycle `cn24.zip`/`cm24.zip` (51 NE candidates,
97 NE committees, 21 tests).

**`indiv24.zip`/`indiv26.zip` pulled, `ne-fec` published, 2026-09-16.**
`indiv24.zip` (4,244,259,029 bytes) and `cn26`/`cm26`/`indiv26.zip`
(2,186,550,443 bytes for `indiv26`) were pulled and normalized. Combined
real NE row counts: **97 candidates, 202 committees, 404,474
contributions** (2024 alone: 51/97/250,610; 2026 alone: 46/105/153,864).

**Two real bugs found on this first full-size pull, fixed same day** (see
`docs/DATA_SOURCES.md`'s FEC section for the full writeup, `ne-fec` commit
`5769573`): `indiv24.zip` has 34 members, not one (a complete `itcont.txt`
plus a byte-for-byte-redundant `by_date/` breakdown of the same rows) --
`filter_ne.py` now prefers the sole top-level member instead of erroring.
`normalize.py` used to truncate-and-overwrite its output CSVs on every
`--cycle` call, silently discarding 2024's rows once 2026 was normalized --
`--cycle` now accepts multiple cycles (or defaults to every cycle under
`data/raw/`) and combines them in one write.

`ne-fec` was published to `github.com/diepjustin/ne-fec` (was local-only)
with a new `ne-fec-weekly.yml` workflow (Sunday, current cycle only, older
cycles restored from cache and combined via the fixed `normalize.py`).
`ne-connect-nightly.yml` was **not** built as part of this — it doesn't
exist for any source yet, so building it just for FEC would be scope creep;
`build_entities.py`/`build_site.py` stay a manual run for now.

**Hub integration done 2026-09-15, extended 2026-09-16.**
`ingest/sources.py`: `load_fec_committees()`, `load_fec_candidates()`,
`load_fec_contributors()` (real rows now, since the 2026-09-16 pull), plus
new `load_fec_contribution_rows()` for the itemized dossier export.
**Correction to this plan's own text below:** "committees and candidates as
organizations" was wrong for candidates — a candidate is a real person, so
`load_fec_candidates()` sets `entity_type="individual"`, which is what
keeps `match.py`'s person guard from ever auto-merging a candidate's name
with a vendor's.

**Pairing deviates from this plan's original "wires `fec` into every
pairing" text, on purpose.** `build/build_entities.py` now splits the
single merged `fec` dict into `fec_orgs` (committees + candidates — keeps
every original pairing: contracts, campaign_finance, lobbying,
disclosures) and `fec_contributors` (individual itemized donors — paired
against `campaign_finance` only). Contributors are deliberately excluded
from the contracts/lobbying/disclosures pairings: those can never
auto-merge (`involves_person`), and with potentially tens of thousands of
contributor keys, pairing them everywhere would flood the review queue for
no benefit. Both still write `Party.source = "fec"`; bit 16 in
`build_site.py`'s `SOURCE_BITS` is unchanged — only the pairing graph is
asymmetric, not the displayed source. `SOURCE_LABELS["fec"]` is now "FEC
Contributions" (was "FEC Committees & Candidates"); `fec_amt` was added to
`INDEX_COLUMNS`, threaded through `figures()`'s JS with the $200-vs-$250
itemization caveat and the donor-state-not-recipient-state caveat.
`SOURCE_PROJECTS["fec"]` still links to `fec.gov/data/`, not `ne-fec`.

Real counts against the pulled data, rebuilt 2026-09-17: **207 fec_org_keys,
29,125 fec_contributor_keys, 138,817 canonical_entities,
entities_in_two_or_more_sources up to 2,190** (was 1,877 at this session's
start, before any FEC work). **awaiting_review is now 14,656** (was 4,896) —
the new campaign_finance × fec_contributors pairing alone nearly tripled the
review queue, which is exactly why contributors were scoped to that one
pairing rather than all four (see above): pairing against contracts/
lobbying/disclosures too, with 29,125 contributor keys, would have been far
worse for no auto-merge benefit. 130 tests passing in `ne-connect` (105→130
across this session's FEC work; +22 in `ne-fec`, now 22 total there).

Bulk files per cycle at `https://www.fec.gov/files/bulk-downloads/<YYYY>/`: `indiv<yy>.zip`, `cm<yy>.zip`, `cn<yy>.zip`, optionally `pas2<yy>.zip`, `oth<yy>.zip`; headers from `data_dictionaries/`. No API key, reproducible snapshots.

- `scripts/download_bulk.py` (stream to `data/raw/<cycle>/`, sha256 in `scrape_meta.json`); `scripts/filter_ne.py` (stream-decode; `STATE == "NE"` from indiv, `CMTE_ST == "NE"` from cm, `CAND_ST == "NE" or CAND_OFFICE_ST == "NE"` from cn; never load indiv whole); `scripts/normalize.py` → `fec_contributions_ne.csv`, `fec_committees_ne.csv`, `fec_candidates_ne.csv`; `check_data.py`; `tests/`.
- Contributions schema: `sub_id, cmte_id, cmte_name, amndt_ind, rpt_tp, transaction_tp, entity_tp, name, city, state, zip, transaction_dt, transaction_amt, other_id, tran_id, file_num, image_num, cycle, source_url, source_snapshot`; `source_url = https://docquery.fec.gov/cgi-bin/fecimg/?<IMAGE_NUM>`. Employer and occupation are kept in raw only, not in processed output (privacy parity with NADC handling).
- Dedup: `sub_id`; fallback `(cycle, image_num, tran_id)`; same `(cmte_id, tran_id)` keeps newest `file_num` as the `include_in_total` analogue. Rewritten from raw each run.
- **Done 2026-09-16.** Hub: bit 16; `load_fec_contributors()` with `entity_type="individual"` when `entity_tp == "IND"` (never auto-merge; only paired against `campaign_finance`, not contracts/lobbying/disclosures -- see above). Committees and candidates as organizations with `source_id`, paired against all four sources as before. Named columns `fec_amt`, `fec_recs`; label "FEC Contributions" with the $200 federal itemization caveat versus Nebraska's $250, and a donor-state-not-recipient-state caveat (`filter_ne.py` filters on the donor's home state).
- **Done 2026-09-16.** Workflow `ne-fec-weekly.yml`: Sunday, current cycle only, older cycles from cache. `ne-connect-nightly.yml` (the hub's own rebuild automation) is explicitly **not** part of this -- it doesn't exist for any source yet; `build_entities.py`/`build_site.py` stay a manual run.

Tests: header gate; NE-only filter; `sub_id` dedupe; person parse; FEC `IND` never auto-merges with a vendor; `fec_contributors` never pairs against contracts/lobbying/disclosures (new `tests/test_build_entities.py`). Risks: indiv zips multi-GB (stream, cache NE slice per cycle) -- realized cost: 4.24 GB (`indiv24.zip`) + 2.19 GB (`indiv26.zip`) pulled and normalized in one session, no timeout issues once run in the background. Effort: 3-5 days (recon+scaffolding+committees/candidates) + 1 day (this pass: indiv pull, pairing split, dollar figure, publish ne-fec).

---

## Review-queue tooling (`pipeline/`), done 2026-09-17

Direct follow-on from Phase 3: `awaiting_review` jumped from 4,896 to 14,656 the
moment `campaign_finance` x `fec_contributors` landed, and `data/manual/
resolutions.csv` had **zero rows** despite existing since this project's first
version -- `Resolution.pair_id` is a truncated SHA256 (`resolve/resolutions.py`),
so a human could never actually hand-write a valid row. There had never been a
working way to record a decision, FEC aside.

Real breakdown of the queue that motivated this (`data/review_queue.csv`, checked
directly): 14,228 fuzzy / 428 `identical_key` (a fast, low-thought yes/no per
`match.py`'s own `Match.kind` doc comment); 8,976 individual x individual, 3,652
organization x organization, 2,028 mixed; by source pair, `campaign_finance`/`fec`
alone is 9,762 of the 14,656.

Built:
- `build/build_entities.py` gained `_city_columns()` -- `left_cities`/
  `right_cities` on every `match_candidates.csv`/`review_queue.csv` row, the
  disambiguating signal a reviewer actually needs for the hardest case
  (`individual` x `individual`), sourced from `Party.cities` (already tracked by
  `campaign_finance` and `fec` contributors, empty for sources that don't track
  it).
- `build/build_review_tool.py` -> `pipeline/review.html`: a single self-contained
  HTML+CSS+JS page (no framework, matches `index.html`'s own embedded-payload
  convention) embedding the full queue, filterable by match kind / entity-type
  combo / source pair / free text. Same/Different/Skip per pair, kept in
  `localStorage` as an in-session convenience only (not the system of record --
  a cache clear must never destroy a real decision).
- `resolve/apply_review.py`: merges the page's exported CSV
  (`left_key,right_key,decision,note`) into `resolutions.csv`, reusing the
  *existing* `Resolution`/`Ledger`/`pair_id` machinery verbatim -- no new
  hashing. `--by` supplies `decided_by` once per session rather than asking the
  browser tool to know who's using it. Idempotent by `pair_id`.
- **`pipeline/` is gitignored, on purpose, and must stay that way**:
  `index.html` publishes from the repo root via GitHub Pages, so a committed
  `pipeline/review.html` would publish the entire *unreviewed* candidate list
  (every individual x individual guess included) right alongside the finished
  site -- a materially bigger exposure than the finished site itself, which only
  ever shows scored/confirmed entities.

Intended rhythm: review a batch in the browser -> export -> `apply_review.py` ->
rerun `build/build_entities.py` (drops decided pairs from the next
`review_queue.csv` automatically, via `ledger.apply()`) -> regenerate
`pipeline/review.html` from the shorter queue -> repeat.

Tests: `_city_columns()` populated when both sides track cities, empty when a
side doesn't (`tests/test_build_entities.py`); `apply_review.py` produces
correctly-hashed `Resolution` rows with the right `decided_by`/`suggested_by`,
and re-running the same export is idempotent, not duplicated
(`tests/test_apply_review.py`, new). `pipeline/review.html`'s own JS is UI, not
covered by the Python suite -- same scope note as every other dossier-rendering
JS in this project.

---

## LLM-suggested review decisions (local Ollama), done 2026-09-17

Direct follow-on: the review-queue tool above made 14,656 pairs *reviewable*,
but 14,656 is still a lot for one person. `resolve/llm_suggest.py` asks a
local model (Ollama, `llama3.1:8b-instruct-q4_K_M` -- free, already running
on the user's machine, already used for `ne-contracts`' AI summaries, no new
API key) about each pair and caches its answer
(`pipeline/llm_suggestions.jsonl`, gitignored, same sensitivity class as
`pipeline/review.html`). `build/build_review_tool.py` shows a cached
suggestion in the detail view, labeled unverified, never pre-selecting a
button -- CLAUDE.md rule 4 stands unchanged, a human still clicks. New
filter/sort in the review page (by suggested decision, by confidence) is the
actual answer to "too many to review": pull up "AI says same, high
confidence" and blitz through agreement cases first.

Prior art found and fixed along the way, not just new code: `build/review.py`
has had a `MODEL_HINTS` guard against a model-like `--by` since the project's
first commit; `resolve/apply_review.py` (built last session) didn't have it
and has been pushed without it -- moved into a shared
`resolutions.validate_decided_by()`, used by both write paths now. A human
overriding a suggestion needed its own column (`suggested_decision`) --
`suggested_by`/`suggested_score` alone couldn't tell "model said different,
human overrode" apart from "model said same, human agreed."

`CLAUDE.md` gained the "Where the LLM is allowed" section this whole feature
needed -- `PLAN.md`'s Phase 4 (below) already referenced it and a
`data/llm_log/`-style convention before either existed; both are real now,
not aspirational, and `resolve/llm_suggest.py`'s `prompt_hash` field is the
first working instance of that convention.

Tests: `tests/test_llm_suggest.py` (new) covers prompt building, response
parsing/validation with an injectable fake model call (never touches the
network, matching this project's `pytest tests/  # no network` invariant),
and the checkpoint's append-only/last-entry-wins/truncate-on-crash recovery;
`tests/test_resolution.py` covers `validate_decided_by` and
`suggested_decision`'s round-trip; `tests/test_apply_review.py` covers real
per-row provenance passthrough and confirms the pre-existing `suggested_by
== "review"` fallback test still passes unmodified.

**Live-benchmarked against the real queue, same day.** 40 real `organization`-
slice pairs run against Ollama on this machine: 20 at `--workers 2` (0.14/s,
143s, 0 errors), 20 more at `--workers 4` (0.18/s, 113s, 0 errors) -- compute-
bound local inference, so concurrency past 2 workers buys only ~28%, not a
linear speedup; `DEFAULT_WORKERS` raised from the original unbenchmarked 2 to
4, the plateau actually measured. Sample reasoning was legible and
appropriately cautious (e.g. flagging a shared token but differing city as
"uncertain" rather than guessing same). At the 4-worker rate, the full
14,656-pair queue is roughly **22-23 hours of wall-clock, local compute** --
worth stating plainly since "a few seconds per pair" undersells it: this is a
job to leave running across a weekend, not an overnight one. A real bug was
also caught and fixed running this: a worker-crash record (raised before
`suggest_pair` builds its own return dict) had no `pair_id`, which would have
`KeyError`ed `load_checkpoint` on the very next run, defeating the whole
resume-on-crash design; fixed by carrying `pair_id`/`left_key`/`right_key`
through from the source row in `main()`'s crash handler.

---

## Phase 4 — Bill summarizer (`ne-bills/`)

Not blocked by, and doesn't block, anything else — sequenced here mostly
because it's the first *generative* case CLAUDE.md's "Where the LLM is
allowed" rules (now real, see above, not just specified) get exercised
against, rather than the suggest-only case those rules were written for.
Enrichment on existing lobbying records, not a
fourth pillar of the co-occurrence model: bills aren't organizations, so this
adds no new source bit.

**4.1 `scripts/scrape_bills.py`.** Pull bill text + metadata from
`nebraskalegislature.gov/bills/view_bill.php?DocumentID=<id>`: bill number,
session, title, introducer, current status, and the statement/text itself
(often a PDF — reuse `ne-contracts/scripts/extract_text.py`'s pypdf/pdfminer
path, same as the C-1 plan in Phase 1). Natural key `(session, bill_number)`;
raw captures immutable, same pattern as every other source.

**4.2 `scripts/summarize.py`.** One LLM call per bill, strictly extractive in
spirit: the prompt receives only the bill text, must cite the specific
section/line behind every claim, and returns a fixed shape — `summary`,
`citations: [{quote, section}]`, `confidence`. A claim with no citation is
dropped, not kept. Logged to `data/llm_log/` per `CLAUDE.md`'s "Where the LLM
is allowed" rules — model, prompt hash, input record id, full response.
Output `bill_summaries.csv`: `bill_id, session, summary, citations_json,
model, prompt_hash, generated_at, source_url` — every summary carries its own
provenance, same as `source_url`/`retrieved_at` everywhere else.

**4.3 Hub join.** `ingest/sources.py` gains `load_bill_positions()` —
lobbying positions already reference bill numbers (`ne-lobbying`'s
`bill_positions.csv`), so this joins a principal's position to that bill's
summary rather than introducing a new entity type. An entity's detail view
can then show "opposed LB1042 — *machine-generated summary, not the bill
text*" linked straight to the real bill.

**Biggest risk:** a hallucinated or misleading summary reaching a reporter as
if it were fact. Mitigate with the citation requirement above, a visible
"AI-generated, verify against the bill" label rendered next to every summary
(not a footnote), and holding it behind a toggle, off by default, until a
sample has been spot-checked by a person.

Tests: citation-required parser rejects an uncited claim; `llm_log` entry
shape; join scoping (a bill with no lobbying position never surfaces).
Effort: not yet scoped — recon (4.1) first to see what the bill-text access
pattern actually looks like before estimating 4.2/4.3.

---

## Automation notes (applied inside each phase above)

**Reusable pattern** from `ne-contracts-daily.yml` and `pages.yml`:
1. Two UTC crons plus the gate step matching `TZ=America/Chicago date +%z` to the cron that fired (`:37-99`); never gate on wall-clock hour.
2. Tests before any network step.
3. `actions/cache/restore@v5` keyed `<prefix>-${{ github.run_id }}`, `restore-keys: <prefix>-`, `fail-on-cache-miss: true` for baselines (`:119-130`).
4. Release fallback: `gh release list … | sort_by(.tagName) | last`, then `gh release download`.
5. Guard rails fail the job before publish.
6. Every night that scrapes also publishes (`ne-contracts/daily.yml` dropped the old Sunday-only gate; see its own comments for why six days of avoidable staleness wasn't worth it) — dispatches `gh workflow run pages.yml`.
7. "Worth caching" check before `cache/save`, save `if: always()`, prune to newest 3 (`:196-224`).
8. `concurrency: cancel-in-progress: false`.

**Hub workflow `ne-connect-nightly.yml` — done 2026-09-17.** The design above
(cross-repo `actions/cache` restore) doesn't work: Actions caches are
strictly repo-scoped, a workflow running in `ne-connect` can never restore a
cache saved by a workflow in `ne-contracts`. What actually shipped, checked
against the real mechanism rather than assumed:

- **Releases, not caches, cross the repo boundary** — the only thing that
  does (`ne-lobbying`'s own monthly backup already proved this, this just
  generalizes it). `ne-contracts/daily.yml`, `ne-campaign-finance/daily.yml`,
  and `ne-fec/ne-fec-weekly.yml` each gained a "Publish a data release for
  ne-connect" step (gzip the processed CSVs, `gh release create` a dated
  tag, prune to newest 3) at the end of their existing publish leg.
  `ne-lobbying` needed no change — its existing monthly release already does
  this — kept on that cadence rather than moved to nightly, an explicit
  choice (smaller change to an already-working pipeline; the hub states
  staleness honestly either way via `retrieval_dates()`).
- `ne-connect-nightly.yml`: one workflow, two jobs (`build`, `deploy`) — not
  a `daily.yml`/`pages.yml` split, since the hub has no scrape of its own to
  separate from a fast rebuild; downloads each sibling's latest release
  (warn-and-continue on a miss, never a hard failure — a stale source is not
  the same failure as an empty build) → `build_entities.py` → `build_site.py`
  → new `build/verify_payload.py` (entity count above an absolute floor and
  within 10% of the previous run's cached summary, no source's key-count
  silently dropping to zero, `d/entities.json`'s rows matching its own
  header) → stage `_site/` → `actions/upload-pages-artifact@v5` →
  `actions/deploy-pages@v5`.
- **Publish via Pages artifact, not git-commit** — `d/fec_rows.json` is
  already 50MB (measured directly) and GitHub hard-rejects any file over
  100MB; committing it nightly was a collision course, the exact problem
  `ne-contracts/pages.yml` already solved this same way. `ne-connect`'s
  GitHub Pages source needed switching from "Deploy from a branch" to
  "GitHub Actions" (`gh api -X PUT repos/.../pages -f build_type=workflow`)
  as an explicit, sequenced, one-time step — never something a workflow run
  does to itself. The previously-committed `index.html`/`d/*.json` on `main`
  are left in the tree for now (not `.gitignore`'d yet); that's a follow-up
  once the new pipeline has run green nightly for about a week, same
  reasoning `ne-contracts` used for its own transition.
- `tests/test_workflows.py` and `build/verify_payload.py`'s own unit tests
  cover this (see Definition of done below).

**Rate-limit budget:** contracts nightly (existing); campaign finance minutes; lobbying nightly ~40 min, weekly ~4 h; SoS ≤ 20 min weekly; FEC download-bound weekly; hub ~5 min. No two scrapers share a host in the same window.

**Risk:** a sibling's release step failing silently would leave the hub building on an ever-staler copy with no loud signal. `verify_payload.py` catches an *empty* build; it does not (yet) alert on a release that's merely gone stale for days — worth watching once this has run for a while, not solved here.

---

## Definition of done, every phase
- Tests pass in every touched project with no network and no `data/`.
- `check_data.py` clean on every output the phase produces.
- `docs/SCHEMA.md` and `docs/DATA_SOURCES.md` updated in the same commit as the code.
- Every new displayed figure carries a source link and retrieval date; the page states any coverage gap.
- The phase's workflow has run green on `workflow_dispatch` at least once before the phase closes.

## Test baseline
ne-connect 91, ne-campaign-finance 43, ne-lobbying 19, ne-contracts existing.

## Total effort
Roughly 25-34 working days across the phases, plus unattended scrape wall-clock (about 18 h in Phase 0, C-1 OCR and FEC downloads later).

---

## Original brief (as written before this plan, 2026-09-08)

# Nebraska Public Database 
The end goal of this project is to have a set of scraper that obtain various public records across multiple Nebraska state websites and updates a central dataset. The scrapers need to check for existing data and prevent duplicates from appearing in the the dataset. Each goverment site will get its own scraper. 

This dataset is for Nebraska journalists to act as a centralized hub for records from the state government. It can include information from the Nebraska State Contracts Database, which I already have a scraper for, Nebraska Leglisature, Nebraska Accountability and Disclosure Commission, the federal election commmision, any other useful database.

## Resources
This is inspired by CalMaters's Power Search, a campaign finance scraper for California. https://github.com/CalMatters/powersearch-download.

At https://github.com/diepjustin/ne-contracts is the existing scraper for Nebraska State Contracts

 Nebraska Public Records Hub — one search box across state contracts, NADC campaign finance, lobbyist registrations, Secretary of State business filings, and the state salary roster. Type a name, see every connection with links to the primary record. Multiplies the value of ne-contracts and every future database. Heavier scraping upfront, huge payoff.

 Cross-database link checker. One search box that hits ne-contracts, NADC donors, lobbyists, SoS filings, 990s, and salaries at once and shows every connection for a name.

 I got a start on this project here https://github.com/diepjustin/ne-connect