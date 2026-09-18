# Schema

Every artifact this pipeline actually produces. Adding a column without
updating this file is incomplete work.

No parquet, no DuckDB, no cents: everything here is plain CSV or JSON, and
money is stored as a float dollar amount (`amount`), matching what each
scraper source already publishes. This is a deliberate departure from the
original design doc — the project never needed a columnar store at this scale,
and floats-as-dollars avoids an extra conversion at every source boundary.

## `data/canonical_entities.csv`

Written by `build/build_entities.py`. One row per (alias, source) — an entity
spanning three spellings in two sources is several rows sharing `entity_id`.

| column | notes |
|---|---|
| `entity_id` | normalized key of the cluster's root; stable as long as the cluster doesn't change |
| `canonical_name` | display name chosen for the whole cluster |
| `alias` | the raw name as this source published it |
| `normalized_key` | `resolve/normalize.py` output for `alias` |
| `source` | `contracts`, `campaign_finance`, `lobbying`, `disclosures`, or `fec` |
| `era` | `modern` (2022+) or `pre2022` (Phase 1.2's legacy tables) — only `campaign_finance` has more than one today; every other source's rows are `modern`. One row per (alias, source, era): a donor active in both eras gets two rows, never summed together |
| `role` | vendor, contributor, principal, etc. — source-specific |
| `entity_type` | `organization` or `individual` |
| `records` | row count behind this alias in its source |
| `amount` | dollar total behind this alias in its source |
| `source_id` | the source's own identifier, where it publishes one (lobbying only, today) |
| `source_url` | link to the primary record, or a search page where no per-record URL exists |

## `data/hard_id_links.csv`, `data/match_candidates.csv`, `data/review_queue.csv`

All three are `Match.as_row()` from `resolve/match.py` (hard-id links use the
`decision: "hard_id"` row shape from `resolve/authority.py` instead):
`left_key, right_key, match_kind, score, key_weight, decision, reason,
left_type, right_type`, plus `left_source`/`right_source`/`vendor_names`/
`contributor_names`/money columns on the scored two (see
`docs/ENTITY_RESOLUTION.md` for what feeds `decision`). `review_queue.csv` is
ordered by dollars at stake, most first — it is meant to be worked top-down.

Two more columns, added 2026-09-17 for `pipeline/review.html` (below):
`left_cities`/`right_cities`, `build_entities.py _city_columns()` — a
`" | "`-joined sample of `Party.cities` on each side, empty where a source
doesn't track city at all (contracts, lobbying, disclosures). The
disambiguating signal a reviewer actually needs for the hardest case
(`individual` x `individual` — 8,976 of 14,656 rows in the queue this added).

## `data/manual/resolutions.csv`

The decision ledger (`resolve/resolutions.py`). Version-controlled, human-
edited, **never machine-overwritten**; overrides the scorer permanently once a
decision is recorded.

| column | notes |
|---|---|
| `pair_id` | stable hash of the sorted key pair |
| `name_key_a` / `name_key_b` | the two normalized keys, sorted |
| `decision` | `same` or `different` |
| `decided_by` | a person's name or handle — never a model |
| `decided_at` | ISO date |
| `suggested_by` | what proposed the pair: `auto`, `review`, or a model name |
| `suggested_decision` | what the suggestion actually said: `same`, `different`, or `uncertain` — may disagree with `decision` (a human overriding a suggestion) |
| `suggested_score` | the score/confidence at the time of the decision |
| `note` | free text |

## `pipeline/llm_suggestions.jsonl` (local-only, gitignored — never published)

Added 2026-09-17 alongside `resolve/llm_suggest.py`: a triage aid over
`data/review_queue.csv`, not a decision source (`CLAUDE.md`'s "Where the LLM
is allowed" — nothing here ever reaches `resolutions.csv` on its own).
Same sensitivity class as `pipeline/review.html`: it holds a local model's
guesses about whether two named individuals are the same person, so it stays
out of git for the same GitHub-Pages-publishing reason.

Append-only JSONL, one record per line, keyed by `resolve/resolutions.py`'s
`pair_id()` (last entry wins on reload — a retried pair's newer line
supersedes its old one, same recovery shape as
`ne-contracts/scripts/generate_ai_summaries.py`'s checkpoint). Shape:

| field | notes |
|---|---|
| `pair_id` | same stable hash `resolutions.csv` uses — the join key `build/build_review_tool.py` uses to attach a suggestion to a queue row |
| `left_key` / `right_key` | the two normalized keys |
| `model` | which local model produced this (e.g. `llama3.1:8b-instruct-q4_K_M`) |
| `decision` | `same`, `different`, or `uncertain` |
| `confidence` | 0–1 float |
| `reasoning` | one factual sentence, built only from data already in the queue row |
| `prompt_hash` | sha256 of the rendered prompt, first 16 hex chars |
| `generated_at` | ISO timestamp |
| `seconds` | how long the call took |

A row can instead be `{"pair_id", "left_key", "right_key", "model", "error"}`
(and sometimes `"raw"`, the unparseable response) when the call failed or the
model's response didn't parse as expected — `resolve/llm_suggest.py` retries
an `"error"` record on its next run rather than treating it as done.

`build/build_review_tool.py` flattens a matching, non-error record onto its
queue row as `llm_model`/`llm_decision`/`llm_confidence`/`llm_reasoning` for
the generated page's detail view. This file is entirely optional: when it
doesn't exist, every row just gets empty `llm_*` fields and the page renders
exactly as it did before this feature existed.

## `pipeline/review.html` (local-only, gitignored — never published)

Added 2026-09-17 because `resolutions.csv` had never actually been used:
`pair_id` is a truncated SHA256 (`resolve/resolutions.py`'s `pair_id()`), which
a human cannot hand-write in a spreadsheet, so there had never been a working
way to record a decision. `build/build_review_tool.py` reads
`data/review_queue.csv` and embeds every row verbatim as JSON into this one
self-contained HTML+CSS+JS page (no framework, no external request, same
convention as `index.html`'s own embedded payload) — filterable by
`match_kind`, entity-type combo, and source pair. **This must never be
committed**: `index.html` is served from the repo root by GitHub Pages, so a
committed `pipeline/` would publish the entire *unreviewed* candidate list —
every individual x individual name-collision guess — right alongside the
finished site. `.gitignore`'s `pipeline/` entry is the enforcement; this
paragraph is the reason not to remove it.

A click on Same/Different is kept in the browser's `localStorage` as a
session convenience only (an accidental reload shouldn't lose progress), not
as the system of record — a cache clear must never be able to destroy a real
decision. When `pipeline/llm_suggestions.jsonl` exists, the detail view shows
a suggestion (labeled unverified, never pre-selecting a button), and a click
captures that pair's `llm_model`/`llm_decision`/`llm_confidence` into the
decision *at the moment of the click* — not re-derived later, since the cache
can be regenerated between a session and an export. **Export decisions**
downloads `left_key,right_key,decision,note,suggested_by,suggested_decision,
suggested_score` (`decision` is `same`/`different`; the last three columns
are empty for a pair with no suggestion shown) for whatever's been decided so
far; `resolve/apply_review.py <export.csv> --by "name"` is the other half,
turning that export into real `Resolution` rows via the *existing*
`Resolution`/`Ledger`/`pair_id` machinery (no new hashing) and saving them
into `resolutions.csv`, using the export's own `suggested_by`/
`suggested_decision`/`suggested_score` when present or falling back to
`suggested_by="review"` when a pair had no suggestion. The intended rhythm is
export-and-merge often, not one long session held only in `localStorage`.

## `data/entities_summary.json`

Aggregate counts `build/build_entities.py` writes for the page header and
README: entity count, alias count, hard-id-link count, awaiting-review count,
human-decision count.

## `d/entities.json`

The lazily-fetched search index (`build/build_site.py`), fetched only once a
search actually needs it — see that file's module docstring for why it's one
file rather than chunked. Shape: `{"columns": [...], "rows": [[...], ...]}`.
Header-driven so a later phase (SoS, FEC) can append a column without any
existing reader having to change:

`name, bits, contract_amt, contract_recs, contrib_amt, contrib_recs,
lobby_recs, lobby_id, aliases, contrib_amt_legacy, contrib_recs_legacy,
disclosure_recs, fec_recs, disclosure_ids, fec_amt`

`bits` is a source bitmask (`contracts=1, campaign_finance=2, lobbying=4,
disclosures=32, fec=16` — 8 is reserved for SoS, Phase 2, blocked; see
`SOURCE_BITS` in `build_site.py`). `aliases` lists the entity's *other*
spellings, empty when there's only the one. `lobby_id` is the lobbying
source's principal id, empty when lobbying isn't one of the entity's
sources. `contrib_amt`/`contrib_recs` are modern (2022+) campaign-finance
money only as of Phase 1.4; `contrib_amt_legacy`/`contrib_recs_legacy` is the
pre-2022 figure. The two are never summed — `build_site.py`'s JS renders them
as two lines when both are present. `disclosure_recs` (Phase 1.5) is a C-1/C-2
filer's item count; there is no `disclosure_amt` — a financial disclosure has
no dollar concept, unlike every other source here. `fec_recs` (Phase 3) is a
committee's, candidate's, or contributor's own record count. `fec_amt`
(added once `indiv24.zip`/`indiv26.zip` were pulled) is itemized individual
contributions only — FEC's own $200 itemization floor, not Nebraska's $250,
and filtered on the *donor's* home state, so this is "Nebraskans giving to
any federal committee," not "money given to a Nebraska candidate." See
`SOURCE_LABELS["fec"]`'s caveat text in `build_site.py` for the exact wording
shown on the page.

## `index.html`'s inline payload

The cross-source entities (2+ sources) only, rendered as full objects rather
than the compact array above — small enough (a few hundred KB) that the extra
verbosity costs nothing and buys richer per-alias detail (each alias's own
`sources` and `url`) than the lazy index carries. Built by
`build_site.py build_entities()`; see that function for the exact shape.

## Upstream: `ne-campaign-finance`'s C-1/C-2 artifacts

Built 2026-09-15 (`PLAN.md` 1.5). `c1_filings.csv` (filers) is read by
`ingest/sources.py load_disclosure_filers()` as of Phase 1.5's hub
integration, also 2026-09-15 — `source="disclosures"`, `role="filer"`,
`entity_type="individual"` always, so match.py's person guard means these
never auto-merge. `financial_interests.csv` (counterparty organizations named
*in* a disclosure) is deliberately **not** ingested yet: a real check of that
scraper's output found several item types (`real_property`,
`other_financial_interest`, `gift`) whose text comes from a line-fallback
parser that can pick up the form's own instructional boilerplate as if it
were a filer's actual answer (e.g. `"personal residence need not be
reported."`) — shipping that into `canonical_entities.csv` would put fake
organizations in a public search index. `income_source`/
`business_association`/`creditor` use a more reliable numbered-entry parser,
but splitting ingestion by item_type felt like a judgment call worth a human
decision rather than a silent overnight default; see
`load_disclosure_filers()`'s docstring.

`data/processed/c1_filings.csv` (`scripts/scrape_c1.py`): one row per C-1/C-2
filing found in the NADC search grid, `disclosure_id, year, filer_name_raw,
filer_office, filed_method, filing_reason, filed_date, document_url,
retrieved_at`. `disclosure_id` is the state's own GUID for a Manual (scanned)
filing, or a deterministic hash for an Electronic filing (which the grid never
exposes an id for at all — see that script's module docstring on the
`__doPostBack` mystery). `document_url` is a working link for every row: a
direct PDF for Manual, the search page itself for Electronic, since the state
does not host a static URL for an e-filed report.

`data/processed/financial_interests.csv` (`scripts/build_financial_interests.py`,
post-2022-07-11 only) and `data/processed/financial_interests_legacy.csv`
(`scripts/normalize_legacy_c1.py`, pre-2022-07-11, `era="pre2022"` plus
`source_form`) share one shape: `disclosure_id, item_type, counterparty_name_raw,
detail, source_url, retrieved_at, ocr`. `item_type` is one of `income_source,
business_association, financial_institution, stock, real_property,
other_financial_interest, creditor, gift, potential_conflict_of_interest`.
`ocr` is `True` only for rows extracted from a scanned PDF with no text layer
via `pytesseract` — confirmed the common case for Manual filings (75% of a
real sample), so a caller must not treat an `ocr: True` row at the same
confidence as a text-layer or legacy row. Never rewrites the state's own
words (CLAUDE.md rule 1) — see `DATA_SOURCES.md`'s C-1/C-2 entry for the
known limitation that a mostly-blank filing's instructional prose can leak
into `counterparty_name_raw` on the line-fallback extraction path.

## Upstream: `ne-fec`'s processed artifacts

Built and hub-wired 2026-09-15 (`PLAN.md` Phase 3); `ne-fec` itself was
published to GitHub once `indiv24.zip`/`indiv26.zip` were pulled (see
`docs/DATA_SOURCES.md`'s FEC section for the URL and its weekly refresh
workflow). Every `source_url` still points at fec.gov's own data pages, not
at `ne-fec`, so nothing here depends on that repo staying up.

`data/fec_committees_ne.csv` (`scripts/normalize.py`): one row per Nebraska
committee, `cmte_id, cmte_name, treasurer_name, city, state, zip,
cmte_designation, cmte_type, cmte_party_affiliation, org_type,
connected_org_name, cand_id, cycle, source_url, source_snapshot`.
`ingest/sources.py load_fec_committees()` reads this as `source="fec",
role="committee", entity_type="organization"` always.

`data/fec_candidates_ne.csv`: one row per Nebraska candidate, `cand_id,
cand_name, cand_party_affiliation, cand_election_yr, cand_office_st,
cand_office, cand_office_district, cand_ici, cand_status, cand_pcc, city,
state, zip, cycle, source_url, source_snapshot`. `load_fec_candidates()`
reads this as `entity_type="individual"` always — a candidate is a real
person; PLAN.md's original Phase 3 text said "organizations", which would
have let match.py auto-merge a candidate's name with a vendor's on
similarity alone. Deviation noted here and in `PLAN.md`.

`data/fec_contributions_ne.csv`: `sub_id, cmte_id, cmte_name, amndt_ind,
rpt_tp, transaction_tp, entity_tp, name, city, state, zip, transaction_dt,
transaction_amt, other_id, tran_id, file_num, image_num, cycle, source_url,
source_snapshot`. Real rows since `indiv24.zip`/`indiv26.zip` (individual
itemized contributions, >$200, the only FEC dataset with real dollar
figures) were pulled. `load_fec_contributors()` reads it as
`entity_type="individual"` when `entity_tp == "IND"`, else
`"organization"` (a PAC, a corporation making an independent expenditure,
etc); `load_fec_contribution_rows()` reads the same file into the
`d/fec_rows.json` shape below.

## Self-published: `d/fec_rows.json`

Not a cross-fetch: `ne-fec` publishes data files, not a GitHub Pages site,
so there is nothing to fetch from at runtime the way `ne-campaign-finance`/
`ne-lobbying`/`ne-contracts` are below. Instead `build/export_fec.py`
(`write_fec_rows_json()`) reshapes `data/fec_contributions_ne.csv` into this
project's own `d/fec_rows.json` at build time, and `build_site.py`'s
`main()` writes it alongside `d/entities.json` on every build.

Shape: `{raw_name: [[date, amount, cmte_name, city, state, source_url], ...]}`
— same `{name: [[row], ...]}` convention the cross-fetched files below use.
`date` is `YYYY-MM-DD`, reformatted from FEC's raw `MMDDYYYY` by
`ingest/sources.py _fec_date_iso()` so the column sorts lexicographically;
everything else is passed through as published. Keyed by the exact raw
`name` `load_fec_contributors()` recorded (not always the entity's
canonical display name) — `build_site.py`'s JS tries every alias plus the
display name as a lookup key, same pattern `campaignFinanceTxns()` already
uses for `d/rows.json`. **No street address** — the source column never
carries one, and city/state-only matches `docs/PRIVACY.md` rule 2.

## Cross-fetch: `ne-campaign-finance`'s `d/rows.json`

Added 2026-09-15, at the project owner's request to make ne-connect "the
main site" rather than a summary that sends a reporter elsewhere for the
underlying records. ne-connect does not duplicate transaction-level data
into its own build; an entity's detail view fetches
`../ne-campaign-finance/d/rows.json` lazily (once per page load, only on
first expand of an entity with `campaign_finance` in its sources) and
renders the matching rows inline. Same GitHub Pages deployment, not a
third party -- the footer's "nothing loads from a third party" claim still
holds.

`d/rows.json` is `{source_name: [[date, amount, filer_name, org_id, city,
state, description, included, era], ...]}`, built by
`ne-campaign-finance/scripts/build_site.py build_search_index()`. `era` is
`"modern"` (2022+, from `contributions.csv`) or `"pre2022"` (from
`contributions_legacy.csv`, added in this same change) -- both eras share
one list here since a reporter wants every itemized record for a name, but
the dollar totals shown elsewhere are still never summed across eras. Keyed
by the exact raw `source_name` string that scraper recorded, which is not
always this entity's canonical display name (a different source may have
won that pick -- see `_canonical_name()`); ne-connect's JS tries every alias
plus the display name as a lookup key rather than tracking which alias
belongs to which source.

Contracts still has its own bespoke binary search index (not a simple
per-vendor JSON) and disclosures still publishes no itemized, fetchable
payload -- extending this pattern to them needs new export work in those
repos first, tracked as open work rather than done silently.

## Cross-fetch: `ne-lobbying`'s `d/positions.json`

Added 2026-09-15, same request as above. `ne-lobbying/scripts/build_site.py
build_positions_index()` writes `{principal_id: [[legislature, bill,
position, lobbyist, registration_id], ...]}`, deduped on `(legislature,
bill, registration_id, position)` -- the same natural key
`ingest/sources.py load_lobbying_principals()` already uses, since the
Legislature's own pages list some registrations twice.

Unlike campaign finance, this join doesn't need alias-guessing: a lobbying
principal carries its own numeric id (`source_id` in `canonical_entities.csv`,
exposed to the page as `lobby_id` on both the inline entity object --
`build_entities()` in `build_site.py` -- and the lazily-widened one), so
ne-connect's JS looks it up directly as `positionsData[e.lobby_id]`.

## Campaign-finance filers and spending

Added 2026-09-15: campaign-finance committees and candidates ("filers")
are now first-class hub entities, not just the "To" column inside a
contributor's transaction list. `ingest/sources.py` gained
`load_campaign_filers()`/`load_legacy_campaign_filers()` (era-keyed exactly
like `load_contributors()`, `role="filer"`, `entity_type="organization"`
always) and `load_spend_only_filers()` (a filer with real expenditures but
zero itemized receipts -- every one of its contributions was below the
reporting threshold -- still needs an entity, or its spending would be
unreachable; `record_count`/`total_amount` stay 0 for these).

**Real collision risk, handled:** these three loaders' dicts are merged
with `load_contributors()`'s via `{**a, **b, ...}` in
`build/build_entities.py`. A name that happens to be both a contributor and
a filer in the same era would otherwise silently clobber one `Party` on
merge. Every filer dict key carries a `"filer:"` prefix
(`("filer:" + filer_name, era)`) specifically to make that collision
impossible -- confirmed by
`tests/test_sources.py::test_campaign_filer_key_never_collides_with_a_contributor_key`.

**`figures()` guard**: a spend-only filer's `{records: 0, amount: 0}` is
truthy, so without a guard it would render a misleading "$0 · 0 records"
contributions line. `build_site.py`'s `figures()` now skips a source's
summary figure entirely when both `records` and `amount` are zero.

**Cross-fetch: `ne-campaign-finance`'s `d/expenditures.json`.** The
spending-side counterpart to `d/rows.json`: `build_expenditures_index()`
writes `{filer_name: [[date, amount, payee_name, description, city, state,
support_or_oppose, included, era], ...]}` from `expenditures.csv` +
`expenditures_legacy.csv`, era-tagged the same way contributions are.
Deliberately does NOT read `independent_expenditures.csv` -- PLAN.md's own
table notes it is "a subset of expenditures, not extra rows," so reading
both would double-count. ne-connect fetches this lazily (same
alias-guessing lookup as `d/rows.json`, since a filer's raw name isn't
distinguished from a contributor's in the entity object) and renders a
"Campaign spending" table, included in both the itemized detail view and
the per-entity CSV export (`record_type: campaign_finance_expenditure`).

**CSV/formula-injection guard.** Several exported fields (a description, a
payee name) are the state's own verbatim text this project never
rewrites -- if one starts with `=`, `+`, `-`, `@`, a tab, or a carriage
return, Excel/Sheets can read it as a formula on open. `csvCell()` prefixes
such values with a bare `'` before the existing quote-escaping, same fix
applied retroactively to every CSV export this page produces.

**Itemized tables are scrollable and searchable, not an inline dump.** All
four itemized sections (contributions, spending, positions, disclosure
items) render through one shared `itemizedBlock()` helper: a heading, a
text filter box (delegated `input` listener on `list`, live substring
match), and a 320px scrollable table capped at 500 DOM rows with a note
pointing at the CSV download for anything beyond that. The download
button sits above these sections, not below -- real feedback was that a
long table pushed it out of reach. A click anywhere inside `.txns-slot`
(the filter box, a scroll drag, an org-detail link) does not also toggle
the entity closed; without that guard, focusing the filter box collapsed
the whole section.

## Cross-fetch: `ne-campaign-finance`'s `d/disclosure_items.json`

Added 2026-09-15. Unlike campaign finance's alias-guessing, this join needs
none: `disclosure_id` is the state's own filing id, already the exact
`source_id` `load_disclosure_filers()` keys its `Party` objects by.
Entities can hold more than one (a filer with disclosures in different
years), so `build_full_index()`/`build_entities()` expose a
**`disclosure_ids` list**, not a single id like `lobby_id` -- the one
material difference from the lobbying pattern.

`build_disclosure_items_index()` in `ne-campaign-finance/scripts/build_site.py`
writes `{disclosure_id: [[item_type, counterparty_name_raw, detail, ocr,
era], ...]}` from `financial_interests.csv` + `financial_interests_legacy.csv`
(the latter doesn't exist on this machine yet -- read gracefully, same as
every other optional legacy file). The real data-quality caveat from
`load_disclosure_filers()`'s own docstring is unchanged and renders inline:
a line-fallback parser on several item types (`real_property`,
`other_financial_interest`, `gift`) can pick up the form's own
instructional boilerplate as if it were the filer's actual answer --
confirmed live against Rex A Adams's real disclosure ("Type have nothing
to report, write NONE" rendered as an item). `ocr: true` rows (most Manual
filings) are flagged per-row; the state's own text is never rewritten
either way (CLAUDE.md rule 1), only flagged for a reader's confidence.

## Cross-fetch: `ne-contracts`'s `d/rows/<A-Z|_>.json`

Added 2026-09-15, the fourth and (for now) last source to get itemized
detail. Unlike the other three, `ne-contracts` already runs a large,
tightly-verified real search build (`scripts/build_site.py`: a bespoke
binary index -- token files, posting lists, its own selftest/verification
machinery). That script is untouched; a new, fully independent
`scripts/export_vendor_rows.py` reads `nu_contracts.csv` +
`nu_purchase_orders.csv` directly and writes its own export, exactly the
"thin, separate adapter" pattern used everywhere else in this project.

**Sharded, not one file, and this was a real constraint, not a
preference.** A single combined export is ~190 MB -- one vendor alone
(Amazon Capital Services, ~66,900 purchase-order line items) accounts for
~25 MB of it -- well past GitHub's **hard 100 MB per-file push limit**,
confirmed by actually building the unsharded file and hitting the wall.
`export_vendor_rows.py`'s `shard_key()` buckets by the vendor name's first
character (A-Z, `_` for anything else) into `d/rows/<KEY>.json`: 27 shards,
largest ~42 MB, comfortably under even the 50 MB warning threshold. No
record was truncated to make this fit. ne-connect's JS mirrors the same
`shard_key()` logic (`contractShardKey()`) and fetches only the shard(s) a
looked-up vendor's name and aliases fall into, caching each shard
individually as it's fetched rather than loading all 27 up front.

**Not committed at all -- `d/rows/` is gitignored,** matching every other
build artifact in `ne-contracts`. That repo stopped committing its `d/`
payload entirely after doing so once bloated `.git` to 546 MB (see the
comment at the top of `.github/workflows/pages.yml`); committing a 190 MB
sharded export would reintroduce the same problem at a larger scale.
`pages.yml` instead runs `export_vendor_rows.py` at deploy time, placed
after the workflow's own build-directory cleanup step (so a `rows/` entry
isn't swept away as an unrecognized build dir) and before the payload gets
cached for the next run, so it rides along in that cache entry the same
way `build_site.py`'s own search payload already does.

Row shape: `[document_number, document_type, entity_name, amount,
begin_date, end_date, status, detail_url]`, keyed by the exact raw
"Vendor" string -- the same key `ingest/sources.py load_contract_vendors()`
already uses, so the alias-guessing lookup is identical to campaign
finance's.

## Dedup contract, by source

See `PLAN.md`'s dedup table — it is the one place this is kept current, since
it changes per source as each new phase lands.
