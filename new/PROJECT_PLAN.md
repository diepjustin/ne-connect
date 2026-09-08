# Project plan

Phases are dependency-ordered. Finish a phase before starting the next. Each phase
ends with something a reporter could actually use.

---

## Phase 0 — Repo skeleton

**Goal:** `make setup && make test` works on a clean checkout.

- [ ] `pyproject.toml` with deps: httpx, polars, duckdb, rapidfuzz, python-dateutil,
      pytest, ruff
- [ ] `Makefile` targets: setup, scrape, build, test, serve, clean
- [ ] `.gitignore` excluding `data/raw/**` except `manifest.json`, and
      `data/llm_log/**`
- [ ] `scrapers/base.py` — shared HTTP client with rate limiting, retry with
      backoff, on-disk cache keyed by URL, User-Agent from env `NE_CONNECT_UA`
- [ ] `pipeline/manifest.py` — write/verify capture manifests

**Done when:** an empty pipeline run produces `data/dist/status.json`.

---

## Phase 1 — Contracts (the anchor dataset)

Justin already shipped a scraper for this at
`diepjustin.github.io/ne-contracts`. Port it in rather than rewriting.

**Goal:** contracts in the canonical schema, in parquet.

- [ ] `scrapers/contracts.py` — capture from statecontracts.nebraska.gov
- [ ] Map to the `contracts` table in `docs/SCHEMA.md`
- [ ] Vendor names extracted into a `parties` staging table with role=`vendor`
- [ ] Agencies extracted with role=`agency`

**Done when:** `data/clean/contracts.parquet` exists and row counts match the
existing ne-contracts site within 1%.

---

## Phase 2 — Name normalization

This is the core of the product. Build it before adding more sources, because every
source depends on it.

- [ ] `resolve/normalize.py` — `normalize_org()` and `normalize_person()`
- [ ] Nebraska-specific alias table (`resolve/aliases.yml`): NPPD, OPPD, LES, UNL /
      UNO / UNMC / UNK / "Board of Regents" / "University of Nebraska", DHHS, NDOT
      vs. NDOR, NDEE vs. NDEQ
- [ ] Legal-suffix stripping, abbreviation expansion, punctuation folding, `d/b/a`
      and `c/o` handling
- [ ] Person names: last/first/middle/suffix parse, nickname table, initial handling
- [ ] Tests against `tests/fixtures/name_variants.csv` — every row must resolve to
      the expected key

**Done when:** the fixture suite passes at 100% and normalization is deterministic
(same input, same output, no network, no model).

---

## Phase 3 — Campaign finance (NADC)

Two eras, two acquisition paths. See `docs/DATA_SOURCES.md` for the details.

- [ ] `scrapers/nadc_modern.py` — pull the CSV data download from the current
      e-filing system (receipts and expenditures), forward from 2022
- [ ] `scrapers/nadc_historical.py` — ingest the pre-2022 bulk download; read
      `nadc_tables.rtf` for field meanings and encode them in `docs/SCHEMA.md`
- [ ] Optional cross-check: The Accountability Project has cleaned NE contributions
      (1985–2021) and expenditures (1999–2021). Use as a **validation set**, not as
      the primary source — confirm licensing before redistributing any of it.
- [ ] Map both eras into one `contributions` table and one `expenditures` table with
      an `era` column and a `source_form` column (B1AB, B2A, B4A, B5, B72, B73 for
      contributions; B1D, B2B, B4B1 for expenditures)

**Done when:** a reporter can search a donor name and get every contribution with a
link to the filing.

---

## Phase 4 — First cross-source join

The first moment the tool justifies itself.

- [ ] `resolve/match.py` — blocking + fuzzy scoring, emits candidate pairs with a
      score and a human-readable reason string
- [ ] `data/manual/resolutions.csv` — the decision file; schema in
      `docs/ENTITY_RESOLUTION.md`
- [ ] `pipeline/build_entities.py` — assemble `canonical_entities` and
      `entity_appearances` from decisions + high-confidence auto-matches
- [ ] Ship `data/dist/vendors_who_donate.csv` — every state vendor that also appears
      as a campaign contributor, with amounts and dates on both sides

**Done when:** that CSV exists and a human has reviewed the first 100 matches.

---

## Phase 5 — The site

- [ ] `site/index.html` + `site/app.js` — DuckDB-WASM loads parquet from
      `data/dist/`, one search box
- [ ] Results grouped by source with counts and totals
- [ ] Entity page: aliases, cross-source timeline, co-occurring entities
- [ ] Every row: source, retrieval date, link to primary record
- [ ] Staleness banner driven by `status.json`
- [ ] CSV export of any result set
- [ ] Case-file export: markdown with every record and link, for a reporter's notes

See `docs/UI_SPEC.md` before writing any frontend code.

**Done when:** it loads in under 3 seconds on a mid-range laptop and works with
JavaScript's network tab showing no calls to any third party.

---

## Phase 6 — Lobbying

- [ ] `scrapers/lobby.py` — registration by principal, registration by lobbyist,
      quarterly reports, and statements of activity from the Clerk of the
      Legislature
- [ ] Statements of activity give bill-level positions (support/oppose per LB per
      principal) — model this as its own table; it is the most valuable part
- [ ] Join principals to contract vendors via the resolver

**Done when:** searching a company shows its lobbyists, its spending, and the bills
it took positions on.

---

## Phase 7 — People-side sources

- [ ] `scrapers/salaries.py` — state employee roster from DAS
- [ ] `scrapers/c1.py` — NADC Statements of Financial Interest (Form C-1): the
      businesses, income sources, and creditors officials disclose
- [ ] Person resolution turned on (see `docs/PRIVACY.md` first — this phase has
      judgment calls, not just engineering)

---

## Phase 8 — Secretary of State business filings

Free search only returns name, account number, type, status; details pages hold
registered agent and principal office. Bulk CSV is a paid batch service
($15/1,000 records). **Do not bulk-buy the registry.**

- [ ] `scrapers/sos.py` — on-demand lookup for entities that already appear in
      another dataset, cached indefinitely, refreshed on request
- [ ] Registered-agent and shared-address graph edges

---

## Phase 9 — Optional LLM layer

Only after everything above works without it.

- [ ] `resolve/adjudicate.py` — ambiguous-band match review, writes proposals a
      human accepts or rejects into `resolutions.csv`
- [ ] `pipeline/summarize.py` — precomputed per-entity footprint summaries, every
      figure cited to a record ID, regenerated weekly in Actions
- [ ] Never runs in the browser. Never on a reader's request. Batch only.

---

## Phase 10 — Publish the scrapers as a reusable package

The point is other Nebraska newsrooms can use this.

- [ ] Extract `scrapers/` into an installable `ne-records` package
- [ ] A README per source: what it holds, how to get it, known gotchas, update
      cadence
- [ ] Open license, documented data dictionary, example notebooks

---

## Explicitly out of scope

- Generating story drafts, headlines, or any reader-facing prose
- Any claim about whether a pattern is improper
- Scraping any source whose terms forbid it (notably: Nebraska JUSTICE trial court
  records — use CourtListener and published opinions instead)
- Hosting copies of documents the state already serves; link to the state's PDFs
