# Nebraska Public Records Hub (`ne-connect`)

**Status: phases 0–2 built.** 44 tests. Three sources in: contracts, campaign finance
and lobbying. **529 canonical entities**, of which **13 appear in all three sources** —
a state vendor who donates *and* lobbies — plus **1,893 pairs awaiting human review**,
ordered by money at stake. `resolve/resolutions.csv` is the decision ledger and is
currently **empty**; no human has ruled on anything yet.

Lobbying principal ids **short-circuit the matcher** (`resolve/authority.py`): records
sharing a source-native id are one entity by construction, linked without scoring.
Decisions taken: phase 0 first; individuals fully in scope, and therefore never
auto-merged.

One search box across every Nebraska public dataset we hold. Type a name, get every
hit grouped by source, each row linking to the primary record, plus a connections
panel showing where the same entity appears in two or more sources. The tool surfaces
overlaps and hands over the documents. It never asserts a story.

| | |
|---|---|
| [Verdict](#verdict) | is this feasible |
| [What changed after checking](#what-changed-after-checking) | four corrections to the proposal |
| [Sources](#sources) | tiers, and what each is actually worth |
| [Entity resolution](#entity-resolution) | the actual product |
| [Architecture](#architecture) | and why not DuckDB-WASM yet |
| [Build order](#build-order) | realistic version |
| [Decisions](#decisions) | before anything gets built |

---

## Verdict

**Feasible, and the core idea is right.** This is what CalMatters, OpenSecrets and the
Accountability Project already do; nobody does it for Nebraska. The entity-resolution
design in the proposal — deterministic normalization, then blocking, then fuzzy match
within blocks, with a human-reviewed `resolutions.csv` that overrides the algorithm
forever — is the correct architecture, not a naive one.

Three things in the proposal are wrong or risky, and one is a judgment call worth
making deliberately rather than by default. All four are addressed below.

**The timeline is the weakest part.** Five weeks is off by roughly 3–4x. The evidence
is in the next folder over: `ne-campaign-finance` is the *easiest* source in the whole
plan — stable bulk CSV, no auth, published layout PDFs — and it still produced three
schema surprises the documentation actively got wrong (misnamed columns, transaction
IDs the docs called unique that aren't, a type renamed mid-corpus). Every new source
will have its own version of that. Budget accordingly.

## What changed after checking

**1. Skip the Accountability Project files; go to the state.** Their repo has **no
LICENSE file**, so the redistribution question you flagged has no clean answer — and it
doesn't need one, because their repo holds *cleaning scripts and diaries*, not the bulk
data. The pre-2022 NADC data is published by the state directly
(`nebraska.gov/nadc_data/nadc_data.zip`, ~63 pipe-delimited files) and the Omaha
World-Herald open-sourced a parser for it ([`OWH-projects/nadc_data`](https://github.com/OWH-projects/nadc_data)).
Pulling from the primary source dissolves the licensing question and gives better
provenance — "we obtained it from the state" beats "we redistributed someone's copy."
Use their diaries as *documentation*; they're genuinely excellent and they quantify the
dirt (~0.1% missing key fields, ~0.6% exact duplicates). They also have a NE `lobbying`
folder worth reading before writing that scraper.

**2. Independent expenditures are already solved.** Not in the proposal, but relevant to
sequencing: NADC's bulk expenditures extract carries support/oppose, target candidate and
jurisdiction. `ne-campaign-finance` already emits 5,928 IE rows for 2022–2026. That's a
strong lead-generating table on day one.

**3. Don't bet the architecture on DuckDB-WASM.** It works, but it adds a large fixed
cost — tens of MB of WASM before a single row of data — to solve a problem v1 doesn't
have. Worse, it implies committing Parquet to git, and **this repo already learned that
lesson expensively**: `ne-contracts` put ~100 MB payloads into git history, `.git`
reached 546 MB, and the fix was to build the payload inside the Pages workflow artifact
and never commit it. Repeating that with Parquet would repeat the outcome. Use
`ne-contracts`' proven pattern for v1 (precomputed chunked JSON, client-side search,
built in CI, never committed), measure the real payload, and revisit DuckDB-WASM as a
v2 experiment with actual numbers in hand.

**4. Organizations only in v1 — for editorial reasons, not just technical ones.** A
cross-source search over *individuals* is a dossier builder: NADC donor records carry
home address, employer and occupation; the salary roster adds compensation; C-1
disclosures add business interests and creditors. Joining those on a person's name
produces a profile no single source publishes. That is a decision for an editor, not a
default that falls out of the schema. The defensible v1: **organizations are searchable
and appear in the connections graph; individuals are searchable within a single
source's results but are not cross-linked.** This also happens to remove most of the
resolution pain, so the cautious choice is the fast one.

## Sources

Tier 1 — bulk-downloadable, build v1 on these:

| Source | Status | Notes |
|---|---|---|
| State contracts | **done** (`ne-contracts`) | 739,605 records, 92 entities |
| NADC campaign finance 2022+ | **done** (`ne-campaign-finance`) | 207,259 rows, 5 tables |
| NADC campaign finance pre-2022 | not started | state zip + OWH parser; different schema and IDs |
| Lobbyist registration & activity | **bill positions done** | `../ne-lobbying/` — Support/Oppose/Neutral per lobbyist × principal × bill, with stable ids. The only source tying a private interest to a specific bill |
| State salary roster | not started | DAS, annual |
| NADC C-1 financial disclosures | not started | businesses, income sources, creditors — genuinely under-read |

Tier 2 — friction:

- **Secretary of State business filings.** The proposal's strategy is right and worth
  keeping verbatim: don't scrape the registry, look up only entities that already appear
  in Tier 1, cache, refresh on demand. Confirm the current per-record batch pricing
  before budgeting anything — treat the $15/1,000 figure as unverified.
- Auditor findings, DHHS license discipline, roll-call votes.

Tier 3 — later: 990s, USAspending, county parcels.

## Entity resolution

This is the product. Keep the proposal's design; it's sound.

1. **Normalize** (`resolve/normalize.py`) — uppercase, strip punctuation and suffixes
   (INC/LLC/CORP/CO), drop trailing account numbers, expand abbreviations (INS →
   INSURANCE), plus Nebraska-specific rules (NPPD/OPPD, UNL, "Board of Regents").
2. **Block** (`resolve/index.py`) on shared *rare* tokens, skipping any token in more
   than 2% of names. This is what makes 1.4 billion possible pairs into 2,254 scored
   ones. No `splink`/`dedupe` dependency proved necessary — stdlib IDF plus `difflib`
   does the job at this scale, and every number stays hand-checkable.
3. **Score, and record why** (`resolve/match.py`) — IDF-weighted token overlap (70%)
   plus character similarity (30%), with a written reason on every pair. Auto-accept
   requires a key more distinctive than any *single* token can be, expressed as a
   multiple of the corpus's rarest-token weight so it doesn't drift as sources are
   added.

   **A known limitation, stated plainly:** rarity cannot separate a distinctive brand
   from an uncommon English word. `PAVERS` scores a higher IDF than `KIEWIT`. So no
   single-token name ever auto-merges, and 158 identical-key pairs sit in review as
   easy yes/no calls rather than being decided by a machine that cannot actually tell.
4. **Human decides** (`resolve/resolutions.py`, `build/review.py`). Every decision goes
   to a version-controlled `resolutions.csv` that overrides the scorer permanently.
   `--by` must name a person; the CLI refuses anything that looks like a model name. An
   LLM may fill `suggested_by`, never `decided_by`.

   The case that justifies all of it: **`J P MORGAN SECURITIES` vs `P J MORGAN`** —
   identical tokens, $647M of contracts between them, and two unrelated companies (a
   Wall Street bank and an Omaha real estate firm). No scorer can separate those. A
   person can.
5. **`canonical_entities`** — one ID per real-world entity, with all aliases and the
   source each alias came from. An entity is labelled with the most complete alias
   available, never with the `entity_id`: that is the alphabetically-first normalized
   key, which for a lobbying entity is usually the *truncated* spelling.

**Before any of the above: authoritative ids** (`resolve/authority.py`). Some identity
is not a guess. When the Legislature assigns a lobbying principal id 2590, every record
carrying 2590 is that principal by construction, so those records are unioned with no
score at all. This is not an optimisation — it recovers links scoring cannot make:

- **Renames.** Principal 2590 is "Time Warner Cable" in the roster and "Charter
  Communications Operating, L..." in the positions table. The company was renamed and
  the id outlived the name. No normalization connects those strings; the id does.
- **Truncation.** The lobbying site cuts names off in its own markup, and 28% of a real
  sample arrived truncated. Grouped by id, those unmatchable strings inherit the full
  name from the detail page.

The pass runs **first**, so a later name match against any one alias attaches the whole
group — one human decision propagates to every record sharing that id, including the
truncated ones, without re-review. Scope, precisely: an id is authoritative *within its
source only*. That 2590 is one registered principal says nothing about whether it is the
same company as contract vendor "CHARTER COMMUNICATIONS". Cross-source linking still
requires matching, and still requires a person.

On the LLM: the proposal's boundary is right — resolve ambiguous names *for review*,
summarize a footprint with every number cited, flag patterns. Never assert wrongdoing,
never merge without a human decision on record. One addition: an LLM suggestion that a
human accepts should be stored in `resolutions.csv` as *human-decided*, with the
suggestion kept alongside it. Otherwise the provenance of the merge is lost.

## Architecture

```
ne-connect/
  README.md              # source of truth
  ingest/                # one thin adapter per source -> a common table shape
  resolve/               # normalize.py, block.py, match.py, resolutions.csv
  build/                 # connections precompute, search index, site build
  data/                  # gitignored; built in CI
  index.html             # the published page
```

**Scrapers stay in their own projects.** `ne-contracts` and `ne-campaign-finance` keep
their own repos, READMEs and caveats, and each publishes clean tables. `ne-connect`
*consumes* those. A broken lobbyist scraper then can't take down campaign finance, and
the per-source caveats — which are where most of the journalism value lives — stay
attached to the data they describe instead of being flattened into one hub.

**Publishing** follows `ne-contracts`: GitHub Actions builds the payload into the Pages
artifact, nothing large is committed.

**Connections panel** precomputed in CI: per canonical entity, a list of (source, role,
count, $ total, date range); entities in ≥2 sources get a badge; a sortable
"most connected" leaderboard for browsing.

**Show your work on every row** — source, retrieval date, original URL, normalization
applied. Keep this; it's what makes the tool quotable.

## Build order

Realistic, and ordered so something useful exists early.

| Phase | Work | Rough size |
|---|---|---|
| 0 | ~~**Vendors who are also donors.**~~ **Done** — 458 strong matches, `data/vendor_donor_report.md`. | done |
| 1 | ~~Normalization + blocking + scoring; `resolutions.csv` and the review loop; `canonical_entities`.~~ **Done.** | done |
| 2 | Lobbyist scraper — **bill positions done** (`../ne-lobbying/`); Form B/C expenses and a full historical sweep remain. | part done |
| 3 | Search UI: one box, grouped results, entity pages, CSV + case-file export. | 1–2 weeks |
| 4 | Pre-2022 NADC; C-1 disclosures; salary roster. | 2–3 weeks |
| 5 | SoS lookups for matched entities only; auditor findings; votes. | open |

**Phase 0 is the whole bet in miniature.** If the vendor↔donor join produces a list
that makes a reporter sit up, the project is worth the rest of the year. If it produces
mush, that's worth knowing in days rather than after building a DuckDB frontend.

## Decisions

1. **People in v1?** Recommendation above: organizations only in the connections graph.
2. **Does `ne-campaign-finance` continue independently?** Recommendation: yes — finish
   its registry phase, since `Org ID` → committee identity is exactly what `ne-connect`
   needs to join on, and it's better built there than here.
3. **SoS budget.** Verify current pricing before committing to Tier 2.
