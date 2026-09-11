# Data sources

One section per source. Keep this current — it is the first thing a new contributor
and a new agent read. If access changes, edit here in the same commit as the code
change.

Status values: `shipped`, `in progress`, `planned`, `blocked`, `rejected`.

---

## Nebraska State Contracts & Purchase Orders

- **Status:** shipped (existing scraper at `diepjustin.github.io/ne-contracts`)
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
- **Update cadence:** weekly

---

## Campaign finance — NADC (modern, 2022 onward)

- **Status:** planned (Phase 3)
- **Publisher:** Nebraska Accountability and Disclosure Commission
- **URL:** https://nadc-e.nebraska.gov/PublicSite/Reports/Reports.aspx
- **Access:** the reports page offers a Data Download that provides CSV downloads of
  receipts or expenditures data. Prefer this over scraping the search UI.
- **Grain:** one row per transaction
- **Notes:**
  - Candidate committees register once they raise/receive/expend more than $5,000 in
    a calendar year
  - Contributors giving more than $250 in a calendar year are itemized; below that
    threshold they are not in the data at all — say so in the UI or reporters will
    misread absence as zero
  - Form B-5 (late contributions, $1,000+ in the 14 days before an election) is a
    separate stream worth flagging
- **Update cadence:** monthly, plus a tighter cadence in the weeks before an
  election

---

## Campaign finance — NADC (historical, pre-2022)

- **Status:** planned (Phase 3)
- **Access:** a bulk download of the older data based on the paper records, linked
  from the NADC filings page. One of the files is `nadc_tables.rtf`, which documents
  the table structure — read it and encode the field meanings in `docs/SCHEMA.md`.
- **Search UI:** https://www.nebraska.gov/nadc/ccdb/search.cgi
- **Gotcha:** the two eras have different form sets and different field names.
  Never silently concatenate them; carry an `era` column.

### Validation set (not a primary source)

The Accountability Project (publicaccountability.org) publishes cleaned Nebraska
contributions (1985–2021, ~239,918 records, forms B1AB/B2A/B4A/B5/B72/B73) and
expenditures (1999–2021, ~141,082 records, forms B1D/B2B/B4B1). Use these to
validate our own parse of the state files. **Confirm licensing before
redistributing any of it in `data/dist/`.**

---

## Lobbying — Clerk of the Legislature

- **Status:** planned (Phase 6)
- **Publisher:** Office of the Clerk of the Legislature (NADC does *not* hold these
  filings, despite regulating lobbying)
- **URLs:**
  - Reports index: https://nebraskalegislature.gov/reports/lobby.php
  - Viewer: https://nebraskalegislature.gov/lobbyist/view.php
  - Current principal + lobbyist list (PDF):
    https://nebraskalegislature.gov/FloorDocs/Current/PDF/Lobby/principallist.pdf
- **Available reports:** registration by principal, registration by lobbyist,
  quarterly report by lobbyist, quarterly report by principal,
  lobbyist/principal statement of activity, counts
- **The valuable one:** Statements of Activity, filed within 45 days after the end
  of session, disclose which legislative bills the lobbyist supported or opposed on
  behalf of the principal. That is a bill-level position table nobody else has
  structured.
- **Gotchas:**
  - Documents not filed electronically before 2015 must be requested by email from
    lobby@leg.ne.gov — mark those years as incomplete in the UI
  - The principal list PDF is a layout-heavy table; parse carefully and check
    totals against the counts report
- **Update cadence:** quarterly, plus post-session for statements of activity

---

## State employee salaries

- **Status:** planned (Phase 7)
- **Publisher:** Nebraska Department of Administrative Services
- **Notes:** verify the current publication format before building; if it is only
  available by records request, file one and store the response in `data/manual/`
  with the request letter alongside it.

---

## Statements of Financial Interest (Form C-1) and Conflicts (Form C-2)

- **Status:** planned (Phase 7)
- **Publisher:** NADC
- **Access:** searchable on the NADC filings site. For C-2, individual filers are
  found by typing the last name into the organization name box and selecting the
  "Individual Supplemental Filer" type — an interface quirk worth encoding in the
  scraper.
- **Why it matters:** C-1 lists officials' own business interests, income sources,
  and creditors. Cross-referenced against contracts, it is the sharpest edge in this
  whole tool.
- **Handle with care:** see `docs/PRIVACY.md`.

---

## Secretary of State business filings

- **Status:** planned (Phase 8)
- **URL:** https://sos.nebraska.gov/business-services/corporate-and-business
- **Free search returns:** name, Secretary of State account number, type, status.
  A details view opens registered agent, principal office, and filed documents.
  Status "Exists" means active.
- **Bulk:** a paid batch service at $15 per 1,000 records
  (https://www.nebraska.gov/SpecialRequestSearches/index.cgi), authorized by
  Neb. Rev. Stat. § 33-101, run by a third party rather than the SOS itself.
- **Our approach:** do not buy the registry. Look up only entities that already
  appear in another dataset, cache results indefinitely, refresh on demand. If a
  targeted batch pull is ever needed, budget it explicitly and record the cost.

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
