# Entity resolution

The whole tool rests on deciding when "AMERITAS LIFE INS" in one dataset and
"Ameritas Life Insurance Corp." in another are the same thing. Get this wrong in the
permissive direction and the tool invents connections that don't exist — which, in a
newsroom tool, is the worst possible failure. Get it wrong in the strict direction
and it misses real ones, which is merely disappointing.

**Bias strict.** A missed match costs a reporter a lead. A false match costs a
correction.

## The pipeline, as built

```
raw names (per source)
  -> normalize (resolve/normalize.py -- deterministic, no network, no model)
  -> authoritative-id short-circuit (resolve/authority.py -- identity by
     construction, no scoring, runs first so a later match attaches the group)
  -> rare-token blocking + candidate pairs (resolve/index.py TokenIndex)
  -> score (resolve/match.py) -> auto / review / reject
  -> human decisions layered on top (resolve/resolutions.py Ledger,
     data/manual/resolutions.csv)
  -> canonical entities assembled (build/build_entities.py)
```

### 1. Normalize

`resolve/normalize.py`. Pure: same input, same output, forever, because
`normalized_key` values are baked into published entity ids. Uppercases, folds
accents, strips punctuation and legal suffixes, expands abbreviations, and
applies `resolve/aliases.yml` (the Nebraska-specific table: NPPD/OPPD/LES/MUD,
UNL/UNO/UNMC/UNK, NDOR→NDOT, etc.) last. People are parsed into last/first and
handled separately. The exact rule set lives in the code, not here — this file
would drift out of sync with it if it tried to duplicate the list.

### 2. Authoritative ids first

`resolve/authority.py`. Some identity needs no scoring: when the Legislature
assigns lobbying principal id 2590, every record carrying 2590 is that same
registered principal by construction, whether the name on it is "Time Warner
Cable" or a table cell truncated to "Associated Beverage Distributors of...".
`short_circuit()` unions every key sharing a `(source, source_id)` pair before
any scoring runs, so a single later name-match against any one alias attaches
the whole group. Scope is precise: an id is authoritative *within its source
only* — it says nothing about whether that principal is the same real-world
company as a contract vendor with a similar name. Cross-source identity still
requires matching, and still requires a person to accept it above the review
floor.

### 3. Block

`resolve/index.py TokenIndex`. Comparing every vendor key to every contributor
key is billions of pairs — not affordable and not necessary, since a real match
shares at least one distinctive token. The index computes inverse document
frequency per token so that sharing a rare token (KIEWIT, OLSSON, HUDL) counts
far more than sharing a common one (SERVICES, COUNTY, NEBRASKA); tokens
appearing in more than `COMMON_TOKEN_SHARE` (2%) of all keys are dropped from
blocking entirely, and any single block is capped at `MAX_BLOCK_SIZE` (400)
rather than allowed to explode. This deliberately favors rarity over token
count: a real single-word Nebraska firm name should not be demoted just for
being one token, the way an early version of this pipeline did.

### 4. Score

`resolve/match.py score_pair()`. Two components, blended:

- **Weighted Jaccard** — token overlap between the two keys, weighted by each
  shared token's IDF, so agreeing on "KIEWIT" outweighs agreeing on "SERVICES".
- **Sequence similarity** — character-level ratio (`difflib.SequenceMatcher`),
  to catch typos overlap alone would miss ("DEP0T" vs "DEPOT").

`score = 0.7 * jaccard + 0.3 * sequence`. Every score carries a `reason` string
naming which shared token was rarest and what each component scored — that
string is what's rendered in the UI, and it's what makes a match something a
reporter can judge for themselves rather than take on faith.

### 5. Decide

`decide()` in `resolve/match.py`:

| band | condition |
|---|---|
| `reject` | score < `REVIEW_FLOOR` (0.60) |
| `auto` | score >= `AUTO_ACCEPT_SCORE` (0.95) **and** the matched key's weight clears `AUTO_WEIGHT_MULTIPLE` (1.15) × the corpus's rarest-possible-token IDF **and** neither side is a person |
| `review` | everything else in [0.60, 1.0] |

`AUTO_WEIGHT_MULTIPLE` is expressed as a multiple of the corpus's own
rarest-token IDF, not an absolute number, so the threshold doesn't silently
drift as more sources are added and the corpus grows. It is also, by
construction, always above 1.0 — a single-token key can never auto-merge no
matter how rare that token is, because IDF alone cannot tell a distinctive
brand from an uncommon English word (in the live data, "PAVERS" scores a
*higher* IDF than "KIEWIT"). That is a real, accepted limitation: only a
person separates the two.

**A person never auto-merges**, in either direction, at any score. Name
collisions among people are common enough in Nebraska (common surnames, small
towns, a $250 itemization threshold that thins the data further) that no score
is trusted to decide it unattended — every match involving an `individual`
lands in review, however high its score.

### 6. Human decisions

`resolve/resolutions.py Ledger` reads `data/manual/resolutions.csv` —
version-controlled, human-edited, **never machine-overwritten** — and applies
`same`/`different` decisions on top of the automated bands before clusters are
assembled. `different` matters as much as `same`: recording it stops the
matcher from re-proposing the same pair on every run. Decisions are transitive
for `same` (union-find, `resolve/resolutions.py UnionFind`); the pipeline does
not currently detect or report a `different` verdict that would split an
otherwise-unioned cluster.

## Not yet built

These were part of the original design and are worth keeping in mind, but
nothing below has landed:

- **LLM adjudication** for the review band. No phase in `PLAN.md` currently
  schedules it. If it lands, the rule stands regardless of phase numbering: its
  output goes to a proposals file, never straight into `resolutions.csv`, and
  every touched entity is labeled machine-proposed until a person approves it.
- **Person-name resolution proper** (nickname tables, `LAST|FIRST_INITIAL`
  blocking, side-by-side review UI for people). Today a person is simply never
  auto-merged; there is no dedicated person-matching pipeline yet.
- A dedicated blocking fallback (soundex/metaphone, n-gram residue matching)
  beyond the rare-token index above.

## Evaluating the resolver

`tests/fixtures/name_variants.csv` holds hand-labeled pairs, exercised by
`tests/test_normalize.py` and `tests/test_join.py`. **Precision is the number
that matters** for auto-accepted matches — a missed match costs a reporter a
lead, a false one costs a correction. Recall can be mediocre; the review queue
exists to catch what the rules miss.
