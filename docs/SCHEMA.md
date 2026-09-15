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
| `source` | `contracts`, `campaign_finance`, or `lobbying` |
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
| `suggested_score` | the score at the time of the decision |
| `note` | free text |

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
lobby_recs, lobby_id, aliases`

`bits` is a source bitmask (`contracts=1, campaign_finance=2, lobbying=4`,
see `SOURCE_BITS` in `build_site.py`). `aliases` lists the entity's *other*
spellings, empty when there's only the one. `lobby_id` is the lobbying
source's principal id, empty when lobbying isn't one of the entity's sources.

## `index.html`'s inline payload

The cross-source entities (2+ sources) only, rendered as full objects rather
than the compact array above — small enough (a few hundred KB) that the extra
verbosity costs nothing and buys richer per-alias detail (each alias's own
`sources` and `url`) than the lazy index carries. Built by
`build_site.py build_entities()`; see that function for the exact shape.

## Upstream: `ne-campaign-finance`'s C-1/C-2 artifacts (not yet ingested here)

Built 2026-09-15 (`PLAN.md` 1.5). Not yet read by `ingest/sources.py` or
`build/build_entities.py` — that wiring is a later phase — but documented here
so the columns are on record before that ingest is written.

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

## Dedup contract, by source

See `PLAN.md`'s dedup table — it is the one place this is kept current, since
it changes per source as each new phase lands.
