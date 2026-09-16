# Goals

Nebraska Public Records Hub — one search box across state contracts, NADC
campaign finance, lobbyist registrations, Secretary of State business filings,
and eventually the state salary roster. Type a name, see every connection with
links to the primary record. Each government site gets its own polite,
deduplicating scraper in its own sibling repo; the hub is a read-only join over
what they publish, dedup lives in each scraper, and nothing is merged on a
judgement call without a recorded human decision.

Inspired by CalMatters' Power Search
(https://github.com/CalMatters/powersearch-download). Existing scraper for
Nebraska State Contracts: `github.com/diepjustin/ne-contracts`.

See `PLAN.md` for the phased implementation plan and current status.

---

# Data sources

One section per source. Keep this current — it is the first thing a new
contributor and a new agent read. If access changes, edit here in the same
commit as the code change.

Status values: `shipped`, `in progress`, `planned`, `blocked`, `rejected`.

---

## Nebraska State Contracts & Purchase Orders

- **Status:** shipped — `github.com/diepjustin/ne-contracts`
- **Publisher:** Nebraska Department of Administrative Services
- **URL:** https://statecontracts.nebraska.gov/
- **Legal basis for publication:** Neb. Rev. Stat. § 84-602.04
- **Covers:** all state agencies, boards and commissions, the University of Nebraska
  system, and the Nebraska State College system
- **Grain:** one row per document; some records carry several documents
  (amendments, renewals, the signed contract)
- **Key fields:** document number, vendor, agency, type, status, begin date, end
  date, amount, description (the state's own words — never rewrite)
- **Gotchas:**
  - Amounts "are as recorded by the state and may include amendments" — do not sum
    naively across amendments without deduplicating by contract
  - Some records have end dates before begin dates; keep the flag, don't fix
  - Documents are served from state servers; link, don't mirror
- **Update cadence:** daily (`ne-contracts-daily.yml`)

---

## Campaign finance — NADC (modern, 2022 onward)

- **Status:** shipped — `github.com/diepjustin/ne-campaign-finance`
- **Publisher:** Nebraska Accountability and Disclosure Commission
- **URL:** https://nadc-e.nebraska.gov/PublicSite/Reports/Reports.aspx
- **Access:** the reports page's Data Download provides CSV exports of receipts
  and expenditures. Scraped, not the search UI.
- **Grain:** one row per transaction
- **Notes:**
  - Candidate committees register once they raise/receive/expend more than $5,000 in
    a calendar year
  - Contributors giving more than $250 in a calendar year are itemized; below that
    threshold they are not in the data at all — say so in the UI or reporters will
    misread absence as zero
  - Form B-5 (late contributions, $1,000+ in the 14 days before an election) is a
    separate stream worth flagging
- **Hub link today:** no per-name search page yet, so the hub links every
  contributor to NADC's own contributions search
  (`ingest/sources.py NADC_CONTRIBUTIONS_SEARCH_URL`), not to a specific record.
  PLAN.md Phase 1 replaces this with a hosted `?q=` search page.
- **Update cadence:** monthly, plus a tighter cadence in the weeks before an
  election

---

## Campaign finance — NADC (historical, pre-2022)

- **Status:** recon done, build planned (`PLAN.md` Phase 1)
- **Access:** `https://nebraska.gov/nadc_data/nadc_data.zip` — no auth, plain GET,
  22.5 MB zipped / 122.9 MB uncompressed, 64 pipe-delimited `.txt` files plus
  `nadc_tables.rtf` (the schema doc) and `DATE_UPDATED.TXT` (`Data last loaded:
  2022-07-11 03:00:20` in the copy fetched 2026-09-11 — confirms the file is
  genuinely frozen, not still updating). Fetched and verified 2026-09-11:
  sha256 `d08d542233...32dee225` (full digest in the recon session; re-derive
  and pin it properly in `scrape_meta.json` when `download_legacy.py` lands).
- **Search UI:** https://www.nebraska.gov/nadc/ccdb/search.cgi
- **Gotcha:** the two eras have different form sets and different field names.
  Never silently concatenate them; carry an `era` column.
- **Gotcha:** dates carry sentinel values (`12/31/9999`, `01/01/0001`,
  `01/01/0900` all seen in `formc1.txt`'s `Date Received` column) — keep the
  flag, don't coerce to a real date.
- **Recon finding that changes the Phase 1.5 plan:** the zip already contains
  `formc1.txt` (81,804 rows, "Statement of Financial Interest"),
  `formc1inc.txt` (10,604 rows, income/business/creditor sources),
  `formc1prop.txt` (3 rows, real/other property — sparsely filled), and
  `formc2.txt` (1,013 rows, "Potential Conflict of Interest Statement") —
  structured, pipe-delimited C-1/C-2 data through 2022-07-11. **1.5's PDF-parsing
  plan is only needed for C-1/C-2 filings after that cutover date**; everything
  before it can be normalized straight from this zip like every other legacy
  form, no OCR or PDF text extraction involved. Update `PLAN.md` 1.5 to split
  on the 2022 boundary before starting it.
- **Privacy flag:** `formc1.txt`'s `Candidate Address` column is a **home
  street address** in plaintext (e.g. `809 1ST AVENUE`), not an office address —
  `docs/PRIVACY.md` rule 2 ("home addresses are never displayed") applies
  directly; strip to city/state/zip before this reaches `canonical_entities.csv`
  or any display, same as the modern contributor data already does.

### Validation set (not a primary source)

The Accountability Project (publicaccountability.org) publishes cleaned Nebraska
contributions (1985–2021, ~239,918 records, forms B1AB/B2A/B4A/B5/B72/B73) and
expenditures (1999–2021, ~141,082 records, forms B1D/B2B/B4B1). Use these to
validate our own parse of the state files. **Confirm licensing before
redistributing any of it.**

---

## Lobbying — Clerk of the Legislature

- **Status:** shipped (positions) / in progress (expenses) —
  `github.com/diepjustin/ne-lobbying`
- **Publisher:** Office of the Clerk of the Legislature (NADC does *not* hold these
  filings, despite regulating lobbying)
- **URLs:**
  - Reports index: https://nebraskalegislature.gov/reports/lobby.php
  - Viewer: https://nebraskalegislature.gov/lobbyist/view.php
  - Current principal + lobbyist list (PDF):
    https://nebraskalegislature.gov/FloorDocs/Current/PDF/Lobby/principallist.pdf
- **What's collected today:** bill-level positions (Statements of Activity) for
  legislature 109; Form B and Form C expense sweeps in progress (see `PLAN.md`
  Phase 0 for current sweep status). Six historical legislatures (105–108-3)
  are queued for backfill.
- **Gotchas:**
  - Documents not filed electronically before 2015 must be requested by email from
    lobby@leg.ne.gov — mark those years as incomplete in the UI
  - The principal list PDF is a layout-heavy table; parse carefully and check
    totals against the counts report
- **Update cadence:** nightly (recent), weekly (current-legislature refresh) once
  `ne-lobbying-daily.yml` lands per `PLAN.md`

---

## State employee salaries

- **Status:** planned (later, not yet phased)
- **Publisher:** Nebraska Department of Administrative Services
- **Notes:** verify the current publication format before building; if it is only
  available by records request, file one and store the response in `data/manual/`
  with the request letter alongside it.

---

## Statements of Financial Interest (Form C-1) and Conflicts (Form C-2)

- **Status:** built 2026-09-15 (`PLAN.md` Phase 1.5), lives in
  `ne-campaign-finance`: `scripts/scrape_c1.py` (search-grid index ->
  `data/processed/c1_filings.csv`), `scripts/build_financial_interests.py`
  (PDF fetch/OCR -> `data/processed/financial_interests.csv`, post-2022-07-11
  only), `scripts/normalize_legacy_c1.py` (the frozen zip's four C-1/C-2 forms
  -> `data/processed/financial_interests_legacy.csv`, same shape). Verified
  end-to-end against the live site (20 filings scraped across two 2023 result
  pages, one Electronic PDF resolved and parsed, six Manual PDFs downloaded
  and parsed) and against the real legacy zip (11,523 items from 81,256
  formc1 filers). 115 tests passing in `ne-campaign-finance`.
- **Publisher:** NADC
- **Pre-2022-07-11 access:** `nadc_data.zip`'s `formc1.txt` (81,804 rows),
  `formc1inc.txt` (10,604 rows), `formc1prop.txt` (3 rows), `formc2.txt`
  (1,013 rows) — see the historical campaign-finance entry above. No scraper;
  `normalize_legacy_c1.py` joins them on `(Candidate ID, Date Received)`, per
  `nadc_tables.rtf`'s own "Use along with Date Received to link to FORM10"
  note. `formc1inc`'s `Type of Inocome` code (confirmed against
  `nadc_tables.rtf`'s FORM10 section) is `I`=Source of Income,
  `B`=Business Association, `F`=Financial Institution, `S`=Issuers of Stock,
  `C`=Creditors, `G`=Gifts. **Privacy:** `formc1`'s `Candidate Address` (a home
  street address) is read only long enough to be dropped —
  `strip_to_city_state_zip()` is the sole function that touches it, and no
  output column carries a street address at all.
- **2018–present access:** a dedicated public search page —
  `https://nadc-e.nebraska.gov/PublicSite/SearchPages/Search.aspx
  ?SearchTypeCodeHook=86C705B4-76BE-4FD9-B9A0-B607711F8A3A`, titled "Statements
  of Financial Interests (C-1)". No login. Filing Year dropdown only goes back
  to 2018; `scrape_c1.py` writes every filing regardless of year, and
  `build_financial_interests.py` only processes `year >= 2023` (2022
  straddles the legacy freeze date and is skipped rather than guessed at —
  see that script's docstring).
- **Classic ASP.NET WebForms**, not a JSON API: `__VIEWSTATE` /
  `__EVENTVALIDATION` / `__doPostBack`. Every search and every page turn is a
  full form-field replay (not the async/UpdatePanel partial-postback shape —
  that 500s). Results grid paginates 10/page by default with a *windowed*
  pager (page 1 links only to pages 2–11, same shape as
  `ne-lobbying/scripts/lobby.py`'s bill pager) — `scrape_c1.py` re-reads the
  pager after every page rather than trusting the first page's links.
  Raw responses aren't cacheable by content (every response carries a fresh
  `__VIEWSTATE`), so `scrape_c1.py`'s `PageCache` caches *parsed rows* per
  `(year, filed_method, page)` instead — a resumable, content-level cache
  rather than lobby.py's request-byte cache.
- **The `__doPostBack` mystery, solved (2026-09-14, confirmed both by
  replaying raw HTTP and by driving a real browser session):** every row's
  "View" link looks identical, but its control id comes in exactly two
  shapes tied to **Filed Method**, confirmed by filtering the live page to
  Filed Method=Electronic and seeing every resulting row use the postback
  form:
  - **Manual** (scanned paper filing) → `colActions_sub_actManualView0N` →
    a plain `Configurable.handlePopup('../Reporting/DocumentImagePopup.aspx
    ?PFD_FilingID=<guid>')` — a real, stable, unauthenticated GET URL.
  - **Electronic** (typed, e-filed) → `colActions_sub_actView0N` →
    `__doPostBack(...)`. Clicking it in a live browser session showed why:
    the server does a full synchronous postback and re-renders the entire
    search page with the C-1 rendered fresh as a PDF, embedded inline as
    `<iframe src="data:application/pdf;base64,...">` — **there is no
    server-hosted URL for an Electronic filing's PDF at all**; it exists only
    as bytes in that one response. `scrape_c1.resolve_electronic_pdf()`
    replays that exact postback (verified live: decodes to a valid,
    born-digital PDF) on demand for the PDF pipeline. Because no static URL
    exists, `c1_filings.csv`'s `document_url` for an Electronic row points at
    the search page itself (the same "stopgap door" pattern 0.7 already used
    for campaign-finance entities) rather than a fabricated per-filing link.
- **Text-layer / OCR, refined 2026-09-15 with real fetches of both
  populations:**
  - **Manual (scanned) filings**: of 4 real 2023 samples, 3 of 4 (75%)
    extract zero characters via `pypdf`/`pdfminer` — OCR (PyMuPDF render +
    `pytesseract`) is the *primary* path for this population, not a
    fallback. OCR quality on a photographed, hand-filled form is rough (a
    real sample produced fragments like `"Fal M LalWd"` for a handwritten
    line) — every row extracted this way carries `ocr: true` in
    `financial_interests.csv` so a downstream reader can treat it with
    appropriately lower confidence, never at face value with a verbatim
    text-layer row.
  - **Electronic (e-filed) filings**: the one sample resolved via the
    postback dance is a clean, born-digital PDF with a full pypdf text
    layer — no OCR needed. This makes sense in hindsight: the state only has
    an *image* to scan for a filing that arrived on paper.
- **Item extraction is a best-effort text segmentation, not a full field
  parse.** `build_financial_interests.py` splits each filing's text by its
  `ITEM N` headers and extracts either numbered entries (`"1.) Name 1a.)
  detail"`, Items 6/7/11) or one row per line (Items 8/9/10, which aren't
  numbered in the real form). The state's own words are never rewritten
  (CLAUDE.md rule 1) — but on a mostly-blank filing with no numbered entries,
  the line-fallback path can pick up the item's own instructional prose as if
  it were a filer's answer (the all-caps-title filter catches printed
  headers like "REAL PROPERTY OF THE FILER IN NEBRASKA" but not mixed-case
  instructional paragraphs). Worth a follow-up pass stripping each item's
  known-static instructional text before this is treated as clean data.
- **Why it matters:** C-1 lists officials' own business interests, income sources,
  and creditors. Cross-referenced against contracts, it is the sharpest edge in this
  whole tool.
- **Handle with care:** see `docs/PRIVACY.md`.

---

## Secretary of State business filings

- **Status:** blocked (`PLAN.md` Phase 2, gate 2.0 — checked 2026-09-14)
- **URL:** https://sos.nebraska.gov/business-services/corporate-and-business
- **Free search returns:** name, Secretary of State account number, type, status.
  A details view opens registered agent, principal office, and filed documents.
  Status "Exists" means active.
- **Bulk:** a paid batch service at $15 per 1,000 records
  (https://www.nebraska.gov/SpecialRequestSearches/index.cgi), authorized by
  Neb. Rev. Stat. § 33-101, run by a third party rather than the SOS itself.
- **Terms-of-use gate (CLAUDE.md rule 6 / PLAN.md 2.0), checked 2026-09-14:**
  `sos.nebraska.gov/robots.txt` and `www.nebraska.gov/robots.txt` both allow
  crawling of the relevant paths (no `Disallow` on `/business-services/` or
  `/sos/corp/`). The actual free search tool the SOS page links to
  ("Corporation and Business Search") is not hosted on `sos.nebraska.gov` at
  all — it points to `https://www.nebraska.gov/sos/corp/corpsearch.cgi`, a
  legacy Nebraska.gov (Tyler Technologies / NIC) application. That host's own
  site-wide terms — linked from `nebraska.gov`'s footer as "Terms & Conditions"
  and published at **`https://www.nebraska.gov/policies/`** under "Nebraska Use
  Policy" (a separate page from the unrelated "AI Resident Assistant Terms and
  Conditions" at `/policies/ai.html`, which only governs the site's chatbot) —
  explicitly forbid automated access. Exact quoted text, "Site Conduct"
  section:
  > "You may not without our prior written permission use any computer code,
  > data mining software, 'robot,' 'bot,' 'spider,' 'scraper' or other
  > automatic device, or program, algorithm or methodology having similar
  > processes or functionality, or any manual process, to monitor or copy any
  > of the Web pages, data or content found on this Site or accessed through
  > this Site."
  This is a blanket prohibition on scraping/bots without prior written
  permission — not limited to bulk or commercial use — and it governs the
  `www.nebraska.gov` host that serves the actual search results, so it applies
  directly to `corpsearch.cgi`. Per CLAUDE.md rule 6, this source is **not
  scraped**. No code was written for this phase; recon stopped at the gate.
- **If this ever gets revisited:** the path forward is requesting written
  permission from Nebraska.gov/Tyler Technologies (contact via
  `sos.corp@nebraska.gov` or `support@nebraska.gov`) for narrowly-scoped,
  low-volume, per-entity lookups — not a bulk pull, which the state already
  sells separately at $15/1,000 records. Absent that permission, this source
  stays blocked; do not build `ne-sos/` or `scripts/sos.py`.
- **Our approach (moot while blocked):** do not buy the registry either. If
  permission is ever granted, look up only entities that already appear in
  another dataset, cache results indefinitely, refresh on demand.

---

## FEC federal campaign finance

- **Status:** recon and scaffolding done, hub integration done 2026-09-15
  (`PLAN.md` Phase 3) — committees and candidates only; individual itemized
  contributions (`indiv24.zip`) not pulled, see below.
- **Repo:** `github.com/diepjustin/ne-fec` (local-only so far — no GitHub
  remote, not pushed anywhere; stays local until a human decides to publish
  it).
- **URL:** bulk files at `https://www.fec.gov/files/bulk-downloads/<YYYY>/`
  (`cn<yy>.zip` candidates, `cm<yy>.zip` committees, `indiv<yy>.zip`
  individual contributions, `pas2<yy>.zip`/`oth<yy>.zip` inter-committee
  transactions). No API key needed — this is FEC's own public
  reproducible-snapshot download tree, distinct from the rate-limited
  `api.open.fec.gov` API, which has its own separate terms that do not apply
  here.
- **Terms-of-use gate (CLAUDE.md rule 6), checked 2026-09-15:**
  `https://www.fec.gov/robots.txt` has no `Disallow` covering
  `/files/bulk-downloads/` (its disallow list targets the FEC's *search*
  endpoints — `/data/candidates/?*`, `/data/receipts/?*`, `/search/?*`, etc.
  — not the static bulk-download tree). No terms-of-use page on `fec.gov`
  forbidding automated or bulk access was found. The one substantive legal
  restriction that does apply is FEC's ["Sale or use of contributor
  information"](https://www.fec.gov/updates/sale-or-use-contributor-information/)
  notice (citing the Federal Election Campaign Act), quoted exactly:
  > "information about individual contributors taken from FEC reports cannot
  > be sold or used for soliciting contributions (including any political or
  > charitable contribution) or for any commercial purpose."
  That same notice explicitly exempts this project's use:
  > "Commission regulations provide that the restriction does not apply to
  > the use of individual contributor information in newspapers, magazines,
  > books or similar communications, as long as the principal purpose of the
  > communication is not to solicit contributions or conduct commercial
  > activity."
  Per CLAUDE.md rule 6, this is **not blocked** — bulk download proceeded.
  This restriction is also why `EMPLOYER`/`OCCUPATION` never reach processed
  output regardless (privacy parity with NADC handling, `docs/PRIVACY.md`).
- **Scale:** `indiv<yy>.zip` (itemized individual contributions, >$200) is
  multi-GB — 4.24 GB for the 2024 cycle alone, confirmed via HEAD request.
  `cn<yy>.zip` (356 KB) and `cm<yy>.zip` (883 KB) for 2024 are trivially
  small by comparison. `ne-fec/scripts/download_bulk.py` streams to disk in
  fixed-size chunks (never buffers a whole file); `filter_ne.py` stream-
  decodes and filters line by line so the national `indiv` file is never
  materialized as a list. A real pull and timing of a full `indiv<yy>.zip`
  has **not** been done yet — budget it as a bounded weekly run, not part of
  routine work; see `ne-fec/README.md` "What's still open."
- **Validated against real data:** pulled the real 2024-cycle `cn24.zip` and
  `cm24.zip` and ran the full pipeline end to end — **51 Nebraska
  candidates, 97 Nebraska committees**, `check_data.py` clean. 21 tests, no
  network, in `ne-fec/tests/`.
- **Hub integration done 2026-09-15.** `ingest/sources.py` gained
  `load_fec_committees()` (`entity_type="organization"` always) and
  `load_fec_candidates()` (`entity_type="individual"` always — **PLAN.md's
  original Phase 3 text said "committees and candidates as organizations",
  which was wrong**: a candidate is a real person, and match.py's
  `involves_person` guard exists precisely to stop a name like "GRACE,
  DENNIS B." from auto-merging with a vendor on name similarity alone;
  corrected here rather than followed literally). `load_fec_contributors()`
  reads `fec_contributions_ne.csv` (header-only today) and returns `{}`
  cleanly. `build/build_entities.py` wires `fec` into every pairing (bit 16
  in `build_site.py`'s `SOURCE_BITS`). Rebuilt against the real data: 148
  fec keys (51 candidates + 97 committees), **21 of them cross-matched with
  an existing campaign-finance entity** — e.g. Deb Fischer for US Senate,
  the Douglas County Republican and Democratic parties, HDR Inc.'s employee
  PAC. `entities_in_two_or_more_sources` is now 1,734 (`data/` is gitignored,
  so there's no committed prior figure to diff against).
  `SOURCE_LABELS["fec"]` is "FEC Committees & Candidates", not "Federal
  Contributions" — there's no dollar figure to show yet, and the page's
  `retrieval_dates()`/`fec_note` states that gap explicitly (derived from
  `scrape_meta.json` lacking an `"indiv"` key, not from the CSV being
  empty) rather than rendering a `$0` that would misleadingly assert
  "checked, found nothing." `SOURCE_PROJECTS["fec"]` links to
  `https://www.fec.gov/data/` (fec.gov's own front door), not the local-only
  `ne-fec` repo. 113 tests passing in `ne-connect` (8 new).

## Local government budgets — Auditor of Public Accounts

- **Status:** hub integration done 2026-09-16 (see below).
- **Publisher:** Matt Waite (professor whose course this project grew out of)
  — **not this project's own scraper.** Repo:
  `github.com/mattwaite/nebraska-budget-data`, MIT licensed. Cloned read-only
  under the same parent directory as every other sibling, but never pushed
  to, never forked — see `docs/SCHEMA.md`'s "Self-published:
  nebraska-budget-data" for why this project's own build publishes the
  itemized data itself rather than cross-fetching from a live site (there is
  none — the source repo is a one-shot bulk downloader with a committed CSV
  snapshot, no CI, no recurring cadence).
- **Original source:** the Nebraska Auditor of Public Accounts' [Basic Budget
  Data Query](https://www.nebraska.gov/auditor/reports/index.cgi?budget=1)
  tool, `nebraska.gov` (a `.gov` domain). Local-government budget filings are
  public record under Nebraska's own budget-filing statutes — the same basis
  `ne-contracts` already treats state contracts under; there is no ambiguity
  about whether this class of government financial data is meant to be
  public.
- **Legal basis for this project's access:** this project does not scrape
  `nebraska.gov` itself — the pull already happened, once, in the source
  repo, which publishes its output under an MIT license permitting reuse.
  What this project does instead — reading an already-published,
  already-licensed CSV the same way it reads every other sibling repo's
  `data/` — carries none of the risk described below.
- **Terms-of-use gate (CLAUDE.md rule 6), checked 2026-09-16 — a recurring
  scraper of this project's own is BLOCKED, same as SoS.** The Auditor's
  Basic Budget Data Query tool is served from `www.nebraska.gov`, and that
  domain's own Terms of Use (`nebraska.gov/policies/`) states, quoted
  exactly:
  > "You may not without our prior written permission use any computer
  > code, data mining software, 'robot,' 'bot,' 'spider,' 'scraper' or other
  > automatic device, or program, algorithm or methodology having similar
  > processes or functionality, or any manual process, to monitor or copy
  > any of the Web pages, data or content found on this Site or accessed
  > through this Site."
  This is the exact same `nebraska.gov` policy that already blocked Phase 2
  (SoS business filings) — `robots.txt` on `www.nebraska.gov` itself doesn't
  disallow the CGI path, but the site's own Terms of Use does, in stronger
  language than a robots.txt disallow. Per CLAUDE.md rule 6, this project
  will not build its own recurring scraper against this endpoint. The
  read-only clone of `nebraska-budget-data` above is unaffected — that pull
  is the source repo's own, already done, once, before this project ever
  touched it.
- **Grain:** one row per (subdivision, fiscal year), 1999–2026, 63,934 rows,
  3,240 distinct subdivision names across every county, city, school
  district, fire district, SID, NRD, community college, airport authority,
  etc. in Nebraska.
- **Key fields:** `county_name, subdivision_type, subdivision_name,
  fiscal_year, report_link` (a direct PDF URL to the filed budget form),
  `total_property_tax, valuation, outstanding_debt_total,
  total_resources_available, total_disbursements, unused_budget_authority`
  (often literally `"N/A"` for school districts and some other types).
- **Gotchas:** these are **budget filings** — what a governing board filed
  with the State Auditor, not certified audited actual spending; see the
  page's "Read before quoting" caveat. `subdivision_name` alone is not a safe
  join key: two real bodies share a name across counties in the live file
  (`"Emerson Hubbard Public Schools"`, `"Wakefield CRA"`) — handled by
  `_budget_display_name()`'s county-suffix disambiguation, see
  `docs/SCHEMA.md`. The Auditor's own `subdivision_type` label for cities
  changed from `"Municipalities"` to `"Cities and Villages"` around
  FY2010-2011/2011-2012 — merged by `_BUDGET_TYPE_RELABEL` or 530 cities
  would each split into two entities.
- **Update cadence:** none, and this is not just "not yet automated" — see
  the Terms-of-use gate above. Refreshing this source means the source
  repo's owner re-running his own script and this project re-cloning
  (`git pull` in the sibling directory, then rebuilding), not a scheduled
  workflow of this project's own.
- **Hub integration.** `ingest/sources.py` gained `load_budget_subdivisions()`
  (`entity_type="organization"` always, `total_amount` the most recent fiscal
  year's property tax request only — never summed across years, since unlike
  a one-time contract award a tax request recurs annually) and
  `load_budget_rows()` (the full multi-year history, consumed by
  `build/export_budget.py`, a new module that writes `d/budget_rows.json`,
  this project's own self-published itemized artifact). `build/build_entities.py`
  wires `budgets` into three pairings — contracts, campaign finance, lobbying
  (not disclosures or fec: no plausible counterpart) — bit 64 in
  `build_site.py`'s `SOURCE_BITS`. `resolve/aliases.yml` gained curated
  entries for the state's largest cities (their bare `nebraska-budget-data`
  spelling vs. contracts/lobbying's `"City of X"`); counties need none, since
  a county's own `subdivision_name` already matches exactly. 25 new tests
  across `tests/test_sources.py`, `tests/test_build_site.py`, and the new
  `tests/test_export_budget.py`.

## General Fund Receipts — Department of Revenue

- **Status:** hub integration done 2026-09-16.
- **Publisher:** also Matt Waite, same read-only-clone-no-fork approach.
  Repo: `github.com/mattwaite/nebraska-general-fund-receipts`, MIT licensed
  for the extraction code; the underlying figures are public record (state
  government financial data, not copyrightable facts).
- **Original source:** Nebraska DOR's monthly [General Fund Receipts news
  releases](https://revenue.nebraska.gov/about/news-releases/general-fund-receipts-news-releases)
  (PDF), comparing actual tax receipts to forecast.
- **Legal basis for this project's access:** same as budget data above — no
  scraper of this project's own, reading an already-published MIT-licensed
  extraction.
- **Terms-of-use gate (CLAUDE.md rule 6), checked 2026-09-16 — also
  BLOCKED.** `revenue.nebraska.gov`'s own footer links directly to
  `nebraska.gov/policies/` as its terms of use — the same policy and the
  same anti-scraper clause quoted in the budget-data section above. `robots.txt`
  on `revenue.nebraska.gov` (a standard Drupal file) doesn't disallow
  `/about/news-releases/...`, but the site's own Terms of Use does, in
  stronger language than robots.txt. This project will not build a recurring
  scraper against DOR's news-release archive either.
- **Grain:** one row per (release, fiscal-month) pair, Aug 2016–present, 753
  rows. **Not entity-level** — a single statewide monthly series, never tied
  to any subdivision or organization, so it never touches `SOURCE_BITS`,
  `canonical_entities.csv`, or the resolution pipeline. See
  `docs/SCHEMA.md`'s "Self-published (inline)" section.
- **Key fields:** `data_year, data_month, data_month_name,
  actual_net_receipts, projected_net_receipts, cumulative_actual_net_receipts,
  cumulative_projected_net_receipts`. A given calendar month reappears in
  every release from when it's first reported through the end of that fiscal
  year, which is what lets the source repo's own archive track revisions to
  a month's figures over time (the state sometimes revises a prior month's
  reported actual or forecast without saying so in the release narrative).
- **Gotchas:** the source repo's own extraction already normalized a real
  units inconsistency in the underlying PDFs (some releases print thousands
  of dollars, some print full dollars) — this project surfaces the
  already-clean CSV columns as-is, without re-deriving anything.
- **Update cadence:** none — same reasoning as budget data above (blocked by
  terms of use, not just unscheduled).
- **Hub integration.** `ingest/sources.py load_general_fund_receipts()` is a
  thin, undecimated pass-through of every (release, fiscal-month) row.
  `build/export_budget.py write_general_fund_receipts_json()` writes the full
  history to `d/gfr.json`; `latest_gfr_by_month()` collapses it to one row
  per calendar month (the most recent release's figure) for `build_site.py`
  to inline directly into the page as a small, always-visible section near
  the footer — not gated behind a per-entity click like every itemized
  source above, since it isn't tied to any entity.

---

## Later candidates

Not scheduled. Listed so nobody re-researches them.

- Nebraska State Auditor reports and findings (PDF)
- DHHS professional licensure disciplinary actions
- Legislature roll-call votes and bill text (nebraskalegislature.gov)
- IRS Form 990 bulk data, filtered to Nebraska filers
- USAspending and USDA payments, filtered to Nebraska
- County assessor parcel data (per-county, wildly inconsistent formats)

---

## Rejected

- **Nebraska JUSTICE trial court records** — terms of use restrict automated
  access. Use CourtListener, PACER, and published Supreme Court / Court of Appeals
  opinions instead.
