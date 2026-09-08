# Entity resolution

The whole tool rests on deciding when "AMERITAS LIFE INS" in one dataset and
"Ameritas Life Insurance Corp." in another are the same thing. Get this wrong in the
permissive direction and the tool invents connections that don't exist — which, in a
newsroom tool, is the worst possible failure. Get it wrong in the strict direction
and it misses real ones, which is merely disappointing.

**Bias strict.** A missed match costs a reporter a lead. A false match costs a
correction.

## The pipeline

```
raw names
  -> normalize (deterministic, no network, no model)
  -> block (group plausible candidates cheaply)
  -> score (fuzzy comparison within blocks)
  -> route by score band
       >= 0.95  auto-accept, rule-decided
       0.60-0.95 queue for review
       <  0.60  discard
  -> human decisions recorded in data/manual/resolutions.csv
  -> assemble canonical entities
```

### 1. Normalize

`resolve/normalize.py`. Must be pure: same input, same output, forever. No model
call, no network, no randomness. Rules:

**Organizations**
- Uppercase, fold accents, collapse whitespace
- Strip punctuation except internal `&` (kept, then normalized to `AND`)
- Strip legal suffixes: INC, LLC, LLP, LP, CO, CORP, CORPORATION, COMPANY, LTD,
  PC, PLLC, LC, ASSOCIATION, ASSN, INCORPORATED
- Expand abbreviations: INS→INSURANCE, MFG→MANUFACTURING, CONSTR→CONSTRUCTION,
  SVCS/SERV→SERVICES, TECH→TECHNOLOGY, NATL→NATIONAL, MGMT→MANAGEMENT,
  ENG→ENGINEERING, DIST→DISTRICT, CNTY→COUNTY
- Handle `D/B/A` and `C/O`: split, keep both sides as separate candidate names
- Apply `resolve/aliases.yml` last — the Nebraska-specific table

**People**
- Parse into last, first, middle, suffix; handle `LAST, FIRST M` and `FIRST M LAST`
- Strip titles (MR, MRS, DR, SEN, REP, HON) and suffixes (JR, SR, II, III, IV)
- Apply the nickname table (BOB↔ROBERT, BILL↔WILLIAM, ...)
- Key is `LAST|FIRST_INITIAL` for blocking; full comparison happens in scoring

### 2. Nebraska alias table

`resolve/aliases.yml` is where local knowledge lives. Seed it with at least:

- Utilities: NPPD / Nebraska Public Power District; OPPD / Omaha Public Power
  District; LES / Lincoln Electric System; MUD / Metropolitan Utilities District
- University: UNL, UNO, UNMC, UNK, NCTA, "Board of Regents of the University of
  Nebraska", "University of Nebraska", "NU"
- Agencies with renames: NDOR → NDOT (Roads → Transportation); NDEQ → NDEE
  (Environmental Quality → Environment and Energy); HHS / DHHS
- Colleges: Chadron State, Peru State, Wayne State, "Nebraska State College System"
- NRDs: all 23, each with the full and short form

Every alias entry carries a `source` note explaining why it's there. This file is
public knowledge worth publishing on its own.

### 3. Block

Never compare every name to every name. Blocking keys, in order of preference:

- Exact `name_key`
- First token of `name_key` + zip
- Soundex/metaphone of first two tokens
- 3-gram overlap above a threshold (only for the residue)

### 4. Score

`rapidfuzz` token-set ratio as the base, then adjust:

| signal | effect |
|---|---|
| exact `name_key` match | +0.35 |
| same zip | +0.15 |
| same city + state | +0.10 |
| shared street address | +0.20 |
| one name contains the other as a full token sequence | +0.10 |
| numbers differ (`HOLDINGS II` vs `HOLDINGS III`) | −0.40 |
| one is a person key, other is an org key | −0.50 |
| different state, no other corroboration | −0.15 |

Cap at 1.0. Always emit a `reason` string listing which signals fired — that string
is displayed in the UI and it is what makes a reporter able to judge the match
themselves.

### 5. Decide

`data/manual/resolutions.csv` is the source of truth. It is version-controlled,
human-edited, and **never machine-overwritten**. The pipeline may append proposals
to `data/manual/proposals.csv`; a person moves rows into `resolutions.csv`.

```csv
name_key_a,name_key_b,decision,decided_by,decided_at,note
AMERITAS LIFE INSURANCE,AMERITAS LIFE,same,jdiep,2026-09-14,same Lincoln address in both filings
JOHNSON CONSTRUCTION,JOHNSON CONSTRUCTION OF OMAHA,different,jdiep,2026-09-14,different SOS account numbers
```

`decision` is `same` or `different`. A `different` decision is as important as a
`same` — it stops the matcher from re-proposing forever.

Decisions are transitive for `same` (union-find) but a single `different` between
two members splits the cluster and raises a conflict the pipeline reports rather
than resolves.

### 6. LLM adjudication (Phase 9, optional)

For the 0.60–0.95 band only. The model receives both records with all their fields —
never just the names — and must answer in this shape:

```json
{
  "verdict": "same | different | insufficient",
  "confidence": 0.0,
  "reasoning": "",
  "distinguishing_evidence": ["field: value vs value"],
  "what_would_settle_it": "the record or field a human should check"
}
```

Rules:
- The model's answer lands in `proposals.csv`, never in `resolutions.csv`.
- `insufficient` is a first-class answer and the prompt must say so. A model that
  never says "insufficient" is being pushed to guess.
- Log model, prompt hash, input record IDs, and full response to `data/llm_log/`.
- Anything the model touched is labeled in the UI as machine-proposed until a human
  approves it.

## Person resolution is different

Turn it on only in Phase 7, and read `docs/PRIVACY.md` first. Common Nebraska
surnames plus $250 itemization thresholds plus small towns means confident person
matching often isn't possible. When in doubt, show the reporter both records
side by side and let them decide, rather than merging.

## Evaluating the resolver

`tests/fixtures/name_variants.csv` holds hand-labeled pairs. The suite reports
precision and recall separately. **Precision is the number that matters** — target
above 0.99 on auto-accepted matches. Recall can be mediocre; the review queue exists
to catch what the rules miss.
