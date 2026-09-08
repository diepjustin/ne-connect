"""Candidate matching: blocking, scoring, and routing by confidence band.

Implements the policy in docs/ENTITY_RESOLUTION.md. Read that first — the weights
below are decisions, not tuning knobs to twiddle.

Bias strict. A missed match costs a reporter a lead. A false match costs a
correction.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from rapidfuzz import fuzz

from resolve.normalize import NormalizedName

AUTO_ACCEPT = 0.95
REVIEW_FLOOR = 0.60

# Signal weights. Changing one of these is a policy change: update the doc table in
# docs/ENTITY_RESOLUTION.md in the same commit.
W_EXACT_KEY = 0.35
W_SAME_ZIP = 0.15
W_SAME_CITY_STATE = 0.10
W_SHARED_ADDRESS = 0.20
W_CONTAINMENT = 0.10
P_NUMBER_MISMATCH = -0.40
P_KIND_MISMATCH = -0.50
P_DIFFERENT_STATE = -0.15

ROMAN = {"I", "II", "III", "IV", "V", "VI"}


@dataclass
class Record:
    """A name occurrence from any source table."""

    record_id: str
    source: str
    role: str
    name: NormalizedName
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    address: str | None = None


@dataclass
class CandidatePair:
    a: Record
    b: Record
    score: float
    reasons: list[str] = field(default_factory=list)

    @property
    def band(self) -> str:
        if self.score >= AUTO_ACCEPT:
            return "auto"
        if self.score >= REVIEW_FLOOR:
            return "review"
        return "discard"

    @property
    def reason_text(self) -> str:
        """Human-readable string shown in the UI. This is what lets a reporter
        judge the match themselves, so keep it concrete."""
        return "; ".join(self.reasons)


def _numeric_tokens(key: str) -> set[str]:
    return {t for t in key.split() if t.isdigit() or t in ROMAN}


def block_keys(rec: Record) -> list[str]:
    """Cheap keys that group plausible candidates. Never compare all-to-all."""
    keys: list[str] = []
    if rec.name.kind == "person" and rec.name.person:
        if rec.name.person.block_key:
            keys.append(f"p:{rec.name.person.block_key}")
        return keys
    key = rec.name.key
    if not key:
        return keys
    keys.append(f"k:{key}")
    first_token = key.split()[0] if key.split() else ""
    if first_token:
        if rec.zip:
            keys.append(f"tz:{first_token}|{rec.zip}")
        keys.append(f"t:{first_token}")
    return keys


def build_blocks(records: Iterable[Record]) -> dict[str, list[Record]]:
    blocks: dict[str, list[Record]] = defaultdict(list)
    for rec in records:
        for key in block_keys(rec):
            blocks[key].append(rec)
    # A block containing half the dataset is not a block. Drop the useless ones so
    # scoring stays tractable.
    return {k: v for k, v in blocks.items() if 1 < len(v) <= 500}


def score_pair(a: Record, b: Record) -> CandidatePair:
    reasons: list[str] = []
    key_a, key_b = a.name.key, b.name.key

    base = fuzz.token_set_ratio(key_a, key_b) / 100.0
    score = base * 0.6
    reasons.append(f"name similarity {base:.2f}")

    if key_a and key_a == key_b:
        score += W_EXACT_KEY
        reasons.append("exact normalized name")

    if a.zip and b.zip and a.zip[:5] == b.zip[:5]:
        score += W_SAME_ZIP
        reasons.append(f"same ZIP {a.zip[:5]}")

    if a.city and b.city and a.state and b.state:
        if (a.city.upper(), a.state.upper()) == (b.city.upper(), b.state.upper()):
            score += W_SAME_CITY_STATE
            reasons.append(f"same city {a.city.title()}, {a.state.upper()}")

    if a.address and b.address and a.address.upper() == b.address.upper():
        score += W_SHARED_ADDRESS
        reasons.append("same street address")

    if key_a and key_b and (key_a in key_b or key_b in key_a) and key_a != key_b:
        score += W_CONTAINMENT
        reasons.append("one name contains the other")

    if _numeric_tokens(key_a) != _numeric_tokens(key_b):
        score += P_NUMBER_MISMATCH
        reasons.append("numbering differs")

    if a.name.kind != b.name.kind:
        score += P_KIND_MISMATCH
        reasons.append("one is a person, one is an organization")

    if a.state and b.state and a.state.upper() != b.state.upper():
        score += P_DIFFERENT_STATE
        reasons.append(f"different state ({a.state.upper()} vs {b.state.upper()})")

    return CandidatePair(a=a, b=b, score=max(0.0, min(1.0, score)), reasons=reasons)


def candidates(records: Iterable[Record]) -> list[CandidatePair]:
    """All scored pairs above the discard floor, deduplicated."""
    blocks = build_blocks(records)
    seen: set[tuple[str, str]] = set()
    out: list[CandidatePair] = []
    for group in blocks.values():
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if a.record_id == b.record_id:
                    continue
                pair_key = tuple(sorted((a.record_id, b.record_id)))
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                pair = score_pair(a, b)
                if pair.band != "discard":
                    out.append(pair)
    return sorted(out, key=lambda p: p.score, reverse=True)


# TODO(Phase 4): union-find assembly honoring data/manual/resolutions.csv.
# A `different` decision splits a cluster and must raise a conflict for a human
# rather than being resolved automatically. See docs/ENTITY_RESOLUTION.md.
