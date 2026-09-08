# NE Connect

Cross-database search over Nebraska public records, built for reporters.

One search box covers state contracts, campaign finance, lobbying, salaries,
financial disclosures, and business filings. Type a company or a person, see every
record across every dataset, and click through to the state's own document. Where
the same name appears in more than one dataset, the tool says so — and says nothing
about what that means.

Built by [Justin Diep](https://diepjustin.github.io/). Successor to the
[Nebraska State Contracts database](https://diepjustin.github.io/ne-contracts/).

## What it is not

Not a publishing product. Nothing here writes copy for readers. Not a background
check service. Not a claim that anyone did anything wrong. It is an index over
records the State of Nebraska already publishes, built so a reporter can find them
in twenty minutes instead of a week.

## How it works

```
scrapers/  ->  data/raw/     immutable captures, one dir per source per run
pipeline/  ->  data/clean/   normalized tables (parquet)
resolve/   ->  entity IDs    name normalization, matching, human decisions
pipeline/  ->  data/dist/    what the site loads
site/                        static page; DuckDB-WASM queries the parquet directly
```

GitHub Actions rebuilds weekly and commits `data/dist/`. GitHub Pages serves
`site/`. No server, no database, no third-party requests at runtime.

## Quick start

```bash
make setup          # install
make test           # run the resolver test suite
export NE_CONNECT_UA="NE-Connect (your.email@example.com)"
make scrape         # capture sources into data/raw/
make build          # clean -> resolve -> data/dist/
make verify         # integrity gate; must pass before publishing
make serve          # http://localhost:8000
```

## Working on this with a coding agent

The repo is written to be handed to Claude Code. Start there:

| File | What it's for |
|---|---|
| `CLAUDE.md` | Standing rules. Read first, every session. |
| `PROJECT_PLAN.md` | Dependency-ordered phases. Pick the next unchecked box. |
| `docs/DATA_SOURCES.md` | Every source: how to get it, what's missing from it. |
| `docs/SCHEMA.md` | Table definitions. Update in the same commit as any column change. |
| `docs/ENTITY_RESOLUTION.md` | The matching policy and why it's biased strict. |
| `docs/UI_SPEC.md` | Frontend brief. Read before writing any frontend code. |
| `docs/PRIVACY.md` | The judgment calls about people. Read before Phase 7. |

Slash commands in `.claude/commands/`:

- `/add-source <name>` — research, document, scrape, clean, test, ship a dataset
- `/review-matches` — work the resolution queue and prepare decisions for a human
- `/verify-build` — adversarial pre-publish check

Suggested first session:

```
Read CLAUDE.md and PROJECT_PLAN.md. Phase 0 and Phase 2 are done — the
normalizer in resolve/normalize.py passes its suite and resolve/match.py has the
scoring skeleton. Start Phase 1: port the existing ne-contracts scraper into
scrapers/contracts.py following the pattern in scrapers/base.py, then write
pipeline/clean_contracts.py to produce data/clean/contracts.parquet against the
schema in docs/SCHEMA.md. Do not touch data/manual/.
```

## What's already built

- `resolve/normalize.py` — deterministic org and person name normalization, with a
  Nebraska alias table (`resolve/aliases.yml`) covering agency renames, the NU
  campuses, the public power districts, and the NRDs. 50 tests pass.
- `resolve/match.py` — blocking, scoring with documented weights, confidence bands.
- `scrapers/base.py` — rate-limited client, disk cache, capture manifests, loud
  failure that never silently serves stale data as fresh.
- Decision files under `data/manual/`, which the pipeline reads and never writes.

## What's not built yet

Everything in `PROJECT_PLAN.md` from Phase 1 on. The scrapers, the cleaners, the
entity assembly, and the site are stubs and specs.

## Design commitments

These are in `CLAUDE.md` too, because they're the parts most likely to erode:

1. Agency language is reproduced verbatim or not at all.
2. Every displayed fact links to its primary record with a retrieval date.
3. The tool reports co-occurrence, never wrongdoing.
4. No entity is merged without a recorded human decision.
5. Match confidence and the reason for a match are always visible.
6. Contribution totals are itemized-only and the interface says so every time.
7. Staleness is displayed, never hidden.

## Data and licensing

Source data is public record, published by the State of Nebraska and its agencies.
Contracts data is published under Neb. Rev. Stat. § 84-602.04. Documents are linked
on state servers rather than mirrored. Check `docs/DATA_SOURCES.md` before
redistributing any third-party cleaned dataset.

Code: MIT. Data: check the source.
