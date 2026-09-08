# UI spec

Read this before writing any frontend code.

## Who uses it

A Nebraska reporter on deadline, on a laptop, in a newsroom or a courthouse
hallway. They have a name and twenty minutes. They need to know what the state's
records say about that name and get to the PDFs.

Secondary: an editor checking a reporter's work, and a reporter from another outlet
who found the tool and has no idea what NADC or a C-1 is.

## The job of the interface

1. Find the name.
2. Show what exists, grouped by dataset, with counts and totals.
3. Make the cross-dataset overlap obvious without characterizing it.
4. Get out of the way — every row is a door to a primary document.

## Design direction

The ne-contracts page sets the house style and this should feel like its sibling:
plain, dense, fast, no chrome. Carry that forward rather than inventing a new look.

Specific choices for this project:

- **Density over whitespace.** This is a records tool, not a landing page. A
  reporter should see 30 rows without scrolling. Tight leading, small type, real
  tables — not cards.
- **One accent color, used only for provenance.** Pick a single hue and spend it
  exclusively on the "source" affordance: the little marker that says which dataset a
  row came from, and the link to the primary record. Nothing decorative shares that
  color, so the eye learns that color = document.
- **Confidence rendered as text, not as a colored badge.** "matched: exact name +
  same ZIP (0.97)" reads honestly. A green pill reads as an endorsement.
- **No hero.** The search box is the first thing on the page, above a one-sentence
  description of what's in the index and when it was last updated. That is the whole
  top of the page.
- **Monospace only for identifiers** — document numbers, SOS account numbers,
  record IDs — where character-by-character comparison is the actual task. Not for
  labels or ornament.

Avoid: cards with uniform border-radius and soft shadows; all-caps eyebrow labels;
gradient washes; entrance animations on scroll; an arrow appended to link text. This
should look like a database, because it is one.

## Screens

### 1. Search

```
+--------------------------------------------------------------+
| NE Connect                                                   |
| Nebraska public records, cross-searched.                     |
| 1.2M records · 6 datasets · contracts updated Sep 5, 2026    |
|                                                              |
| [ search a person, company, or agency            ] [Search]  |
|                                                              |
| Datasets in this index:                                      |
|   Contracts    Campaign finance    Lobbying                  |
|   Salaries     Financial disclosures    Business filings     |
+--------------------------------------------------------------+
```

If any dataset is stale or failing, a line appears under the counts naming it and
the date of the last good update. Never hide staleness.

### 2. Results

Grouped by dataset. Each group is collapsible, shows a count and a dollar total
where money applies, and lists rows with the fields that matter for that source.

```
Ameritas Life Insurance Corp.
  also indexed as: AMERITAS LIFE INS · Ameritas Holding Co
  appears in 4 datasets

  Contracts (7 · $2,140,551)                             [expand]
    PO-2024-00913  DHHS       2024-07-01  $412,000   [document]
    ...
  Campaign contributions given (34 · $88,750)            [expand]
  Lobbying — as principal (2026 session, 3 lobbyists)    [expand]
  Business filings (1)                                   [expand]
```

Every row ends with a link to the primary record and carries a retrieval date on
hover or in a details line. Nothing is displayed that can't be clicked through to
the state's own copy.

### 3. Entity page

- Header: display name, all aliases with which dataset each came from, and how each
  alias was decided (rule, human, machine-proposed)
- Timeline: every appearance across every dataset on one date axis. This is the one
  place a visual is worth it — it is what a reporter can't do in a spreadsheet.
- Co-occurring entities: other entities connected by a stated basis
  ("shared registered agent", "same recipient committee, same cycle"), each with the
  evidence records listed. The basis is a description of the join, never a
  characterization.
- Actions: export CSV, export case file (markdown with every record and link)

### 4. Empty and error states

- No results: say what was searched, name the datasets searched, and note the
  itemization threshold — a donor under $250 a year is legitimately absent, and a
  reporter must not read absence as zero.
- Dataset unavailable: name the dataset, the last good update date, and what's
  still searchable without it.

## Non-negotiable interface rules

- Nothing loads from a third-party CDN at runtime. Vendor DuckDB-WASM and any
  fonts into the repo. A reporter searching a sensitive name should not be
  broadcasting it to anyone's analytics.
- No analytics, no tracking, no external fonts, no telemetry. Say so on the page.
- Works with the network tab clean after first load.
- Keyboard-navigable: search field focused on load, results reachable by tab, Enter
  opens the primary document.
- Under 3 seconds to first result on a mid-range laptop over a normal connection.
  If parquet files get big enough to threaten that, split by year and load lazily.
- Every number on screen traces to a record. If a total is the sum of itemized
  contributions only, the UI says so next to the total, every time.

## Copy rules

- Name things as a reporter would: "Campaign contributions given", not "Outbound
  transactions."
- Explain the source in one clause the first time it appears: "Lobbying (Clerk of
  the Legislature)".
- Never use the words suspicious, questionable, improper, red flag, or corrupt
  anywhere in the interface, in any context, including tooltips.
- Where the tool is uncertain, say what's uncertain and what would settle it.
