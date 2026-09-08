"""Scoring a candidate pair, with a reason a reporter can read.

Deliberately not machine learning. Every component of the score is a number
someone can check by hand, and every match carries the sentence that explains
it. A match you cannot explain in one sentence is one you should not publish.

Bands (see decide()):
  auto    >= 0.95 and distinctive enough -- organizations only, never people
  review  0.60-0.95, or anything involving a person
  reject  < 0.60

Nothing in this module merges anything. It proposes; resolutions.py records
what a human decided.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

AUTO_ACCEPT_SCORE = 0.95
REVIEW_FLOOR = 0.60

# Auto-accept needs more distinctiveness than any single token can supply,
# expressed as a multiple of the corpus's rarest-possible-token weight so it
# does not drift as the corpus grows.
#
# Above 1.0 by construction, so a one-token key NEVER auto-merges however rare
# it is. That is deliberate and it is a real limitation: IDF cannot tell a
# distinctive brand from an uncommon English word. In the live data PAVERS
# scores a HIGHER idf than KIEWIT, so "rare" and "trustworthy" are not the same
# thing, and only a person can separate them.
AUTO_WEIGHT_MULTIPLE = 1.15


@dataclass
class Match:
    left: str
    right: str
    score: float
    weight: float
    decision: str
    reason: str
    left_type: str = "organization"
    right_type: str = "organization"

    @property
    def kind(self) -> str:
        """Identical keys vs. a fuzzy guess.

        Worth separating in the review queue: an identical-key pair held back
        only because its name is a single token (KIEWIT, NEBCO, HUDL) is a
        two-second yes/no, while a fuzzy pair needs actual thought. A reviewer
        can clear all of the former in one pass.
        """
        return "identical_key" if self.left == self.right else "fuzzy"

    def as_row(self) -> dict:
        return {
            "left_key": self.left,
            "right_key": self.right,
            "match_kind": self.kind,
            "score": round(self.score, 4),
            "key_weight": round(self.weight, 2),
            "decision": self.decision,
            "reason": self.reason,
            "left_type": self.left_type,
            "right_type": self.right_type,
        }


def weighted_jaccard(left: str, right: str, index) -> float:
    """Token overlap, weighted so sharing KIEWIT counts far more than SERVICES."""
    left_tokens, right_tokens = set(left.split()), set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    shared = left_tokens & right_tokens
    union = left_tokens | right_tokens
    shared_weight = sum(index.idf(t) for t in shared)
    union_weight = sum(index.idf(t) for t in union)
    return shared_weight / union_weight if union_weight else 0.0


def sequence_similarity(left: str, right: str) -> float:
    """Character-level similarity, to catch typos ('DEP0T' for 'DEPOT')."""
    return SequenceMatcher(None, left, right).ratio()


def score_pair(left: str, right: str, index) -> tuple:
    """Combined score plus the human-readable reason for it."""
    if left == right:
        return 1.0, "identical normalized key"

    jaccard = weighted_jaccard(left, right, index)
    sequence = sequence_similarity(left, right)

    # Token overlap leads: word-level agreement is stronger evidence of the same
    # organization than character-level similarity, which happily rates
    # "SIMON" and "SIMONS" as near-identical.
    score = 0.7 * jaccard + 0.3 * sequence

    left_tokens, right_tokens = set(left.split()), set(right.split())
    shared = left_tokens & right_tokens
    if shared:
        rarest = max(shared, key=index.idf)
        reason = (
            f"shares {len(shared)} token(s), rarest {rarest!r} "
            f"(idf {index.idf(rarest):.1f}); token overlap {jaccard:.2f}, "
            f"string similarity {sequence:.2f}"
        )
    else:
        reason = f"no shared tokens; string similarity {sequence:.2f}"
    return score, reason


def auto_weight_floor(index) -> float:
    """Minimum key weight for auto-acceptance, in this corpus's own units."""
    return AUTO_WEIGHT_MULTIPLE * index.max_token_idf


def decide(score: float, weight: float, left_type: str, right_type: str, floor: float) -> str:
    """Which band a scored pair lands in."""
    involves_person = "individual" in (left_type, right_type)
    if score < REVIEW_FLOOR:
        return "reject"
    if score >= AUTO_ACCEPT_SCORE and weight >= floor and not involves_person:
        return "auto"
    return "review"


def match_pair(left: str, right: str, index, left_type="organization", right_type="organization"):
    score, reason = score_pair(left, right, index)
    weight = min(index.weight(left), index.weight(right))
    floor = auto_weight_floor(index)
    decision = decide(score, weight, left_type, right_type, floor)

    if decision == "review" and score >= AUTO_ACCEPT_SCORE:
        if "individual" in (left_type, right_type):
            reason += " -- held for review: involves a person, whose name key collides freely"
        elif weight < floor:
            reason += (
                f" -- held for review: key too generic "
                f"(weight {weight:.1f}, need {floor:.1f})"
            )

    return Match(
        left=left,
        right=right,
        score=score,
        weight=weight,
        decision=decision,
        reason=reason,
        left_type=left_type,
        right_type=right_type,
    )
