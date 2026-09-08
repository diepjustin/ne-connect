"""Token statistics and blocking.

Two jobs, both learned from phase 0's mistakes.

**Rarity, not length.** Phase 0 demoted every single-token key as unreliable and
threw away KIEWIT, OLSSON, NEBCO, HDR and HUDL -- real Nebraska firms whose whole
name is one word, worth $570k in contributions between them. Meanwhile PAVERS
and CONSTRUCTORS are also single tokens and genuinely are risky, because they are
ordinary English words. The distinguishing signal is how rare the token is across
the corpus, not how many tokens there are. That is inverse document frequency.

**Blocking.** 54,259 vendor keys against 25,052 contributor keys is 1.4 billion
pairs. Comparing every one is neither necessary nor affordable: real matches
share at least one distinctive token. Indexing on rare tokens only cuts that to
something small, and skipping common tokens (NEBRASKA, SERVICES, COUNTY) keeps
any single block from exploding.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict

# A token in more than this share of all names carries almost no information and
# would produce a block with tens of thousands of members.
COMMON_TOKEN_SHARE = 0.02

# Even below that share, refuse to build an enormous block.
MAX_BLOCK_SIZE = 400


class TokenIndex:
    """Document frequencies, IDF weights and a rare-token inverted index."""

    def __init__(self, keys):
        self.keys = list(keys)
        self.document_count = max(len(self.keys), 1)

        self.document_frequency = Counter()
        for key in self.keys:
            for token in set(key.split()):
                self.document_frequency[token] += 1

        self.common_tokens = {
            token
            for token, count in self.document_frequency.items()
            if count / self.document_count > COMMON_TOKEN_SHARE
        }

    @property
    def max_token_idf(self) -> float:
        """IDF of the rarest possible token -- one appearing in a single name.

        The natural unit of distinctiveness for this corpus. Thresholds are
        expressed as multiples of it so they survive the corpus growing:
        idf scales with log(N), so any absolute cutoff silently drifts as more
        sources are added.
        """
        return math.log(self.document_count / 2) + 1.0

    def idf(self, token: str) -> float:
        """Rarer token, higher weight. Unseen tokens score as maximally rare."""
        frequency = self.document_frequency.get(token, 0)
        return math.log(self.document_count / (1 + frequency)) + 1.0

    def weight(self, key: str) -> float:
        """Total distinctiveness of a key -- the sum of its tokens' IDF."""
        return sum(self.idf(token) for token in set(key.split()))

    def rare_tokens(self, key: str):
        """The tokens of a key worth blocking on."""
        tokens = set(key.split()) - self.common_tokens
        # A key made entirely of common tokens still needs to be findable, so
        # fall back to its rarest token rather than dropping it from the index.
        if not tokens and key:
            tokens = {min(key.split(), key=lambda t: self.document_frequency.get(t, 0))}
        return tokens


def build_inverted_index(keys, index: TokenIndex):
    """token -> set of keys containing it, for rare tokens only."""
    postings = defaultdict(set)
    for key in keys:
        for token in index.rare_tokens(key):
            postings[token].add(key)
    return postings


def candidate_pairs(left_keys, right_keys, index: TokenIndex):
    """Pairs worth scoring: those sharing at least one rare token.

    Yields (left_key, right_key). Exact-equal keys are included -- the matcher
    scores them 1.0 and they are the cheapest true positives there are.
    """
    postings = build_inverted_index(right_keys, index)
    seen = set()
    for left in left_keys:
        for token in index.rare_tokens(left):
            bucket = postings.get(token)
            if not bucket or len(bucket) > MAX_BLOCK_SIZE:
                continue
            for right in bucket:
                pair = (left, right)
                if pair not in seen:
                    seen.add(pair)
                    yield pair
