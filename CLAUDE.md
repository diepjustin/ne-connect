# CLAUDE.md

Standing instructions for any coding agent working in this repo. Read this first,
then `PLAN.md` for what to build next.

## What this is

NE Connect is a cross-database search tool for Nebraska journalists. One search box
covers Nebraska public records datasets — state contracts, campaign finance,
lobbying, and eventually state salaries, financial disclosures, and business
filings — and shows where the same entity appears in more than one of them, with a
link to every primary record.

It is a **reporting tool**. It is not a publishing product. Nothing in this repo
writes prose for readers.

## Non-negotiable rules

1. **Never rewrite source text.** Agency language is reproduced verbatim or not at
   all. If a field holds the state's own words, it is stored and displayed
   unchanged.
2. **Every displayed fact links to its primary record.** A row without a source URL
   and a retrieval date is a bug.
3. **The tool never asserts wrongdoing.** It reports co-occurrence: "this name
   appears in these datasets." Interpretation is the reporter's job. No output
   may characterize a pattern as improper, suspicious, illegal, or corrupt.
4. **No entity is merged on a judgement call without a recorded human decision.**
   Rule-decided merges are allowed and are defined in `docs/ENTITY_RESOLUTION.md`:
   an identical normalized key, an auto-accept score band (organizations only,
   never a person), or a join on an identifier the source itself publishes.
   Everything below that bar is a proposal, and `data/manual/resolutions.csv`
   decides it.
5. **Confidence is always visible.** Any match shown in the UI carries its score and
   the reason it matched.
6. **Scrapers are polite.** Rate-limit every request, set a descriptive User-Agent
   with a contact address, cache aggressively, and never re-fetch what hasn't
   changed. Respect robots.txt. If a source's terms forbid automated access, do not
   scrape it — note it in `docs/DATA_SOURCES.md` and move on.
7. **Raw captures are immutable within each sibling scraper repo.** Nothing edits a
   scraper's raw capture after the fact; cleaning happens downstream into that
   repo's processed output, which this repo reads read-only.

## Where the LLM is allowed

`PLAN.md`'s bill-summarizer phase and `docs/ENTITY_RESOLUTION.md` both
already assumed this section existed before it did — `resolve/llm_suggest.py`
(review-queue suggestions) is the first real LLM integration in this repo,
so this consolidates what was previously scattered across a few docstrings
into one place to point future work at.

1. **A model may suggest; only a human decides.** `decided_by` in
   `data/manual/resolutions.csv` must never be a model — enforced by
   `resolve/resolutions.py`'s `validate_decided_by()` at every write path
   (`build/review.py`, `resolve/apply_review.py`). What the model actually
   said is kept alongside, never in place of, the human's own decision:
   `suggested_by` (which model), `suggested_decision` (what it said — may
   disagree with `decision`), `suggested_score` (its confidence). A human
   overriding a suggestion is not an edge case to paper over; it is exactly
   the case this provenance trio exists to keep visible.
2. **Nothing an LLM produces reaches a decision file directly.** Its output
   goes to a local cache or proposals file that a review UI reads — never a
   write straight into `resolutions.csv` or any other decision-of-record
   artifact — and stays labeled machine-generated/unverified everywhere it's
   shown.
3. **An LLM-touched artifact that embeds raw source data stays local and
   gitignored**, same rule as `pipeline/review.html` itself: it holds the
   same unreviewed, potentially-sensitive candidate data the queue does, and
   `index.html`'s GitHub-Pages-from-repo-root publishing means anything
   committed is anything published.
4. **Rule 3 applies to model output too.** A suggestion's reasoning never
   characterizes a match as improper, suspicious, illegal, or corrupt — it
   only judges whether two records describe the same real-world entity.
5. **Treat model calls with the same restraint rule 6 asks of scrapers.**
   Cache aggressively; never redundantly re-ask about something already
   answered. A local model still costs real wall-clock time and (for a
   paid API) real money — a starved cache that silently skips retrying a
   failure is worse than a slow one, so a prior error is retried, not
   treated as done.

## Architecture

Federated, not a monorepo. Each source is its own sibling GitHub repo — clone
them all directly under the same parent directory as this one:

```
ne-contracts/           state contracts scraper, its own repo
ne-campaign-finance/    NADC scraper, its own repo
ne-lobbying/            Legislature lobbying scraper, its own repo
ne-connect/             this repo -- the hub, read-only over the above
  ingest/     sources.py -- thin adapters, each sibling's processed CSVs -> a
              common Party shape. Reads local, gitignored data from the
              sibling repos' own working trees (see ingest/sources.py's
              REPO_ROOT comment).
  resolve/    normalize.py, index.py (blocking/IDF), match.py (scoring),
              authority.py (source-id short-circuit), resolutions.py (the
              human decision ledger), apply_review.py (merges a review
              session's decisions into the ledger), llm_suggest.py
              (optional: local-Ollama suggestions for the review queue)
  build/      build_entities.py (the resolution pipeline -> canonical_entities.csv)
              build_site.py (index.html + d/entities.json)
              build_review_tool.py (pipeline/review.html, below)
  data/       rebuilt from the pipeline; only data/manual/ is version-controlled
  index.html  the published page, at the repo root because that's the served path
  d/          the lazily-fetched full search index
  pipeline/   gitignored, local-only tools -- never committed, never published
              (review.html, the review-queue reviewer; llm_suggestions.jsonl,
              resolve/llm_suggest.py's suggestion cache)
```

Runtime: each sibling scrapes on its own GitHub Actions cadence and publishes its
processed CSVs (`ne-*-daily.yml` / weekly, per `PLAN.md` Phase 4). This repo's own
nightly workflow (`ne-connect-nightly.yml`, once it lands) restores those outputs,
rebuilds `canonical_entities.csv` and `index.html`, and publishes via GitHub Pages.
No server, no database, no build step beyond the two Python scripts above.

## Conventions

- Python 3, standard library `csv`/`json` plus `pytest`. No pandas, no DuckDB, no
  parquet — the data fits comfortably in memory as plain CSV/JSON, and adding a
  columnar dependency would buy nothing at this scale.
- Money is a float dollar amount (`amount`), not integer cents — matches what every
  source already publishes.
- `docs/SCHEMA.md` documents every artifact this pipeline writes. Adding or
  changing a column without updating that file is incomplete work.
- Names are stored exactly as published (`alias`), with the normalized form
  (`normalized_key`, from `resolve/normalize.py`) kept in a separate column.
- `tests/` are mandatory for anything touching `resolve/` or `build/`, and must
  include real Nebraska name variants (`tests/fixtures/name_variants.csv`).

## Definition of done for any task

- [ ] `pytest tests -q` passes
- [ ] `docs/SCHEMA.md` updated if an artifact's columns changed
- [ ] `docs/DATA_SOURCES.md` updated if a source was added or its access changed
- [ ] Every new displayed field carries a source URL and a retrieval date
- [ ] `PLAN.md` updated if this closes or changes scope of a listed item

## What to do when a source breaks

A sibling scraper failing does not mean this repo should silently build on stale
data without saying so. `build_site.py`'s `retrieval_dates()` and
`lobbying_coverage()` exist so the page states what it actually has and when it
was last captured — extend that pattern rather than adding a separate status
mechanism. Reporters need to know what they are looking at is stale.
