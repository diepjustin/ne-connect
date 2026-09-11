# CLAUDE.md

Standing instructions for any coding agent working in this repo. Read this first,
then `PROJECT_PLAN.md` for what to build next.

## What this is

NE Connect is a cross-database search tool for Nebraska journalists. One search box
covers Nebraska public records datasets — state contracts, campaign finance,
lobbying, state salaries, financial disclosures, business filings — and shows where
the same entity appears in more than one of them, with a link to every primary
record.

It is a **reporting tool**. It is not a publishing product. Nothing in this repo
writes prose for readers.

## Non-negotiable rules

1. **Never rewrite source text.** Agency language is reproduced verbatim or not at
   all. If a field holds the state's own words, it is stored and displayed
   unchanged.
2. **Every displayed fact links to its primary record.** A row without a source URL
   and a retrieval date is a bug.
3. **The tool never asserts wrongdoing.** It reports co-occurrence: "this name
   appears in these four datasets." Interpretation is the reporter's job. No output
   may characterize a pattern as improper, suspicious, illegal, or corrupt.
4. **No entity is merged on a judgement call without a recorded human decision.**
   Rule-decided merges are allowed and are defined in `docs/ENTITY_RESOLUTION.md`:
   an identical normalized key scoring >= 0.95, or a join on an identifier the
   source itself publishes. Everything below that bar is a proposal, and
   `data/manual/resolutions.csv` decides it.

   *Amended 2026-09-08.* As first written this rule said no entity is merged
   without a human decision, which contradicted the >= 0.95 auto-accept band in
   `docs/ENTITY_RESOLUTION.md`; the two could not both hold. Resolved in favour
   of the score band, with two standing conditions: nothing involving a person
   auto-merges, and the interface states on every view that auto-accepted
   entities are machine-decided and unreviewed.
5. **Confidence is always visible.** Any match shown in the UI carries its score and
   the reason it matched.
6. **Scrapers are polite.** Rate-limit every request, set a descriptive User-Agent
   with a contact address, cache aggressively, and never re-fetch what hasn't
   changed. Respect robots.txt. If a source's terms forbid automated access, do not
   scrape it — note it in `docs/DATA_SOURCES.md` and move on.
7. **Raw captures are immutable.** Scrapers write to `data/raw/` and nothing else
   ever edits those files. All cleaning happens downstream into `data/clean/`.

## Where the LLM is allowed

Allowed:
- Adjudicating ambiguous entity matches in the 0.60–0.90 score band, with written
  reasoning, for human review.
- Summarizing one entity's footprint across datasets, where every number in the
  summary is drawn from a passed-in record and cited by record ID.
- Classifying free-text fields into a fixed, documented taxonomy.

Not allowed:
- Merging entities on its own authority.
- Generating any number, date, dollar amount, or name that is not present in the
  input data.
- Writing narrative, headlines, story drafts, or reader-facing copy.
- Characterizing anyone's conduct.

Every LLM call must be reproducible: log the model, the prompt, the input record
IDs, and the response to `data/llm_log/`. If an LLM output is used in a shipped
artifact, its provenance must be traceable from the UI.

## Architecture

```
scrapers/   one module per source; fetch -> data/raw/<source>/<date>/
resolve/    normalization + candidate matching + canonical entity assembly
pipeline/   orchestration; raw -> clean -> parquet -> data/dist/
site/       static frontend; DuckDB-WASM queries the parquet directly
data/
  raw/      immutable captures (gitignored except manifests)
  clean/    normalized tables
  manual/   human decisions, version-controlled, never machine-overwritten
  dist/     published parquet + json the site loads
```

Runtime: GitHub Actions on a weekly cron builds `data/dist/` and commits it.
GitHub Pages serves `site/`. No server. Vercel is optional and only for the
optional LLM summary endpoint — the site must remain fully functional without it.

## Conventions

- Python 3.11+. `ruff` for lint, `pytest` for tests. Type hints on public functions.
- No pandas in scrapers; use `csv`/`httpx` and keep memory flat. Use `polars` or
  `duckdb` for transforms.
- Every table gets an entry in `docs/SCHEMA.md`. Adding a column without updating
  that file is incomplete work.
- Every scraper writes a `manifest.json` next to its capture: source URL, retrieved
  at (UTC), row count, sha256 of each file.
- Dates are ISO-8601. Money is stored in cents as integers. Names are stored exactly
  as published, with normalization kept in a separate column.
- Tests for `resolve/` are mandatory and must include real Nebraska name variants
  (see `tests/fixtures/name_variants.csv`).

## Definition of done for any task

- [ ] Tests pass (`make test`)
- [ ] `docs/SCHEMA.md` updated if tables changed
- [ ] `docs/DATA_SOURCES.md` updated if a source was added or its access changed
- [ ] Every new displayed field carries source URL + retrieval date
- [ ] No new dependency without a note in the PR description saying why
- [ ] Re-running the pipeline from scratch reproduces the same output

## What to do when a source breaks

Sites change. When a scraper fails: do not silently fall back to stale data. Fail
loudly, keep the last good capture in place, and write the failure to
`data/dist/status.json` so the site can display "campaign finance data last updated
2026-08-14; the source has been unreachable since 2026-09-02." Reporters need to
know what they are looking at is stale.
