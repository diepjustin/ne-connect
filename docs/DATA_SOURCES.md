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

- **Status:** recon done (both eras), build planned (`PLAN.md` Phase 1)
- **Publisher:** NADC
- **Pre-2022-07-11 access:** already collected in bulk, structured, from
  `nadc_data.zip` — see the historical campaign-finance entry above. No scraper
  needed for this era.
- **2018–present access (recon done 2026-09-11):** a dedicated public search
  page — `https://nadc-e.nebraska.gov/PublicSite/SearchPages/Search.aspx
  ?SearchTypeCodeHook=86C705B4-76BE-4FD9-B9A0-B607711F8A3A`, titled "Statements
  of Financial Interests (C-1)". Confirmed live and reachable with no login.
  - **No "Individual Supplemental Filer" trick needed here** — that quirk in
    the original brief may describe finding an individual filer through the
    *Committees/Businesses/Others* search, not this page; this page searches
    C-1 filers directly by last name. Worth a quick check before scraping, but
    not a blocker.
  - Fields: Filing Year (dropdown, **2018–2026 only** — this online system does
    not go back further; 2018–2022-07-11 overlaps the legacy zip's coverage,
    so `scrape_c1.py` needs a dedup rule against `formc1.txt`, not just an era
    split), Last Name, Filed Method (All/Electronic/Manual), Office/Position
    Held, Office Sought, and Filing Reason checkboxes (candidate / annual
    report / left office / newly appointed / **Supplemental Information** —
    this last one is likely the actual C-2 / amendment marker).
  - **Classic ASP.NET WebForms**, not a JSON API: `__VIEWSTATE` /
    `__EVENTVALIDATION` / `__doPostBack`, confirmed via the page's own form
    inputs and script. No `.ashx`/JSON endpoint found. Results grid is
    paginated (page-size 10/25/50, "1 2 3 4 5 6 7 8 9 10 …" — many pages, no
    visible total count) — same POST-body-in-cache-key pattern as
    `ne-lobbying/scripts/lobby.py`'s `Fetcher` (1.5's plan to copy it was
    right).
  - **Every row's "View" link goes straight to a PDF** for most rows, not
    another search hop: `../Reporting/DocumentImagePopup.aspx?PFD_FilingID=<guid>`.
    A minority of rows route through `__doPostBack` instead of a direct GUID
    link — not yet explained; worth checking in 1.5 whether that's electronic
    filings rendering inline HTML rather than a scanned PDF.
  - **Text-layer check done 2026-09-13, confirmed via `pypdf`**: sampled 4 real
    filings from the 2023 grid (GUIDs `a4f60783-2968-4734-93e1-2419010c0a9f`,
    `aaf0ba9f-3ebb-4a16-a753-d0c9c26ec3fb`, `71393121-fa34-4cc1-b0c1-4e34fa5199de`,
    `45b456b0-60aa-4e4f-8bd9-9d1ace264662`; 345 KB-543 KB each). **3 of 4 (75%)
    extract zero characters — scanned images, no text layer at all.** Only one
    had a real text layer (4,347 chars from its first two pages). This
    confirms the suspicion: for 1.5, OCR is the common path, not a fallback
    for the occasional scanned outlier — plan the pipeline (and its review
    cost) around that from the start rather than treating pypdf/pdfminer as
    the primary path with OCR as a hedge.
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

- **Status:** planned (`PLAN.md` Phase 3)
- **URL:** bulk files at https://www.fec.gov/files/bulk-downloads/
- **Access:** no API key needed, reproducible snapshots per election cycle,
  filtered to Nebraska after download.

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
