# Schema

Every table in `data/clean/` and `data/dist/`. Adding a column without updating this
file is incomplete work.

## Conventions

- `*_id` columns are strings, stable across rebuilds, formed as
  `<source>:<natural key>` (e.g. `contracts:PO-2026-004412`)
- Money is integer **cents**. A column named `amount_cents` never holds dollars.
- Dates are ISO-8601 `YYYY-MM-DD`. Timestamps are UTC with a `Z`.
- `name_raw` holds the source's exact string. `name_key` holds the normalized form
  from `resolve/normalize.py`. Both are always present; neither is ever edited by
  hand.
- `source_url` points at the primary record on the publisher's servers.
- `retrieved_at` is when we captured it, not when the state published it.

---

## Source tables

### `contracts`

| column | type | notes |
|---|---|---|
| contract_id | str | `contracts:<document number>` |
| document_number | str | as published |
| vendor_name_raw | str | |
| vendor_name_key | str | |
| agency_name_raw | str | |
| agency_name_key | str | |
| doc_type | str | as published |
| status | str | as published |
| begin_date | date | nullable |
| end_date | date | nullable |
| amount_cents | int | nullable; may include amendments |
| description | str | **verbatim state text; never rewritten** |
| document_urls | list[str] | one record may publish several documents |
| ends_before_begins | bool | data-quality flag, not a correction |
| source_url | str | |
| retrieved_at | timestamp | |

### `contributions`

| column | type | notes |
|---|---|---|
| contribution_id | str | |
| era | str | `pre2022` or `modern` — different form sets |
| source_form | str | B1AB, B2A, B4A, B5, B72, B73 |
| contributor_name_raw | str | |
| contributor_name_key | str | |
| contributor_type | str | individual, business, PAC, party, unknown |
| contributor_city | str | nullable |
| contributor_state | str | nullable |
| contributor_zip | str | nullable |
| recipient_committee_raw | str | |
| recipient_committee_key | str | |
| recipient_candidate_raw | str | nullable |
| office_sought | str | nullable |
| date | date | |
| amount_cents | int | |
| source_url | str | |
| retrieved_at | timestamp | |

Itemization threshold: contributions at or below $250 in a calendar year are not
itemized. The UI must say so wherever totals appear.

### `expenditures`

Same shape as `contributions`, with `payee_*` in place of `contributor_*` and
`source_form` in {B1D, B2B, B4B1}.

### `lobby_registrations`

| column | type | notes |
|---|---|---|
| registration_id | str | |
| session_year | int | |
| principal_name_raw / _key | str | the client |
| lobbyist_name_raw / _key | str | the registered lobbyist |
| lobbyist_firm_raw / _key | str | nullable |
| principal_address | str | |
| compensated | bool | nullable |
| source_url | str | |
| retrieved_at | timestamp | |

### `lobby_positions`

From Statements of Activity. The highest-value table in the repo.

| column | type | notes |
|---|---|---|
| position_id | str | |
| session_year | int | |
| bill_number | str | e.g. `LB1042` |
| principal_name_key | str | |
| lobbyist_name_key | str | |
| position | str | support, oppose, or as published |
| source_url | str | |
| retrieved_at | timestamp | |

### `lobby_expenses`

Quarterly report totals by reporting category, keyed to principal or lobbyist and
calendar quarter.

### `salaries`

| column | type | notes |
|---|---|---|
| salary_id | str | |
| year | int | |
| person_name_raw / _key | str | |
| agency_name_raw / _key | str | |
| job_title | str | |
| salary_cents | int | |
| source_url | str | |
| retrieved_at | timestamp | |

### `financial_interests`

From Form C-1.

| column | type | notes |
|---|---|---|
| disclosure_id | str | |
| year | int | |
| filer_name_raw / _key | str | |
| filer_office | str | |
| item_type | str | business interest, income source, creditor, real property |
| counterparty_name_raw / _key | str | |
| detail | str | verbatim |
| source_url | str | |
| retrieved_at | timestamp | |

### `business_entities`

From the Secretary of State, on-demand lookups only.

| column | type | notes |
|---|---|---|
| sos_account_number | str | the state's unique ID |
| entity_name_raw / _key | str | |
| entity_type | str | LLC, corporation, trade name, etc. |
| status | str | `Exists` means active |
| registered_agent_raw / _key | str | nullable |
| principal_office_address | str | nullable |
| lookup_reason | str | which entity in which table triggered this lookup |
| source_url | str | |
| retrieved_at | timestamp | |

---

## Resolution tables

### `canonical_entities`

| column | type | notes |
|---|---|---|
| entity_id | str | `ent:<slug>-<short hash>`; stable across rebuilds |
| display_name | str | the name a reporter would recognize |
| entity_kind | str | `org` or `person` |
| primary_key_name | str | the normalized key that anchors the cluster |
| source_count | int | how many distinct datasets this entity appears in |
| created_at | timestamp | |

### `entity_aliases`

| column | type | notes |
|---|---|---|
| entity_id | str | |
| name_raw | str | |
| name_key | str | |
| source | str | which table this spelling came from |
| decided_by | str | `rule`, `human`, or `llm-proposed-human-approved` |
| confidence | float | 0–1 |
| reason | str | human-readable: "exact normalized name + same zip" |

### `entity_appearances`

Denormalized index the site queries. One row per (entity, source record).

| column | type | notes |
|---|---|---|
| entity_id | str | |
| source | str | contracts, contributions, lobby_registrations, ... |
| record_id | str | the source table's primary key |
| role | str | vendor, agency, contributor, recipient, principal, lobbyist, employee, filer, counterparty |
| date | date | nullable |
| amount_cents | int | nullable |
| source_url | str | |

### `connections`

Precomputed pairs for the "co-occurring entities" panel.

| column | type | notes |
|---|---|---|
| entity_a | str | |
| entity_b | str | |
| basis | str | shared_address, shared_registered_agent, same_recipient, vendor_and_donor, principal_and_vendor |
| evidence_record_ids | list[str] | |
| first_seen / last_seen | date | |

`basis` values are neutral descriptions of the join, never characterizations.

---

## Site artifacts (`data/dist/`)

- `contracts.parquet`, `contributions.parquet`, ... — the clean tables
- `entities.parquet`, `appearances.parquet`, `connections.parquet`
- `status.json` — per-source last successful update, row count, and any current
  failure; drives the staleness banner
- `manifest.json` — build timestamp, git sha, per-file sha256
