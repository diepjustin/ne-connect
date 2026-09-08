"""The decision ledger: resolutions.csv.

The most valuable artifact this project produces, and the one other newsrooms
can reuse. Every human judgement about whether two names are the same entity is
recorded here, version-controlled, and **overrides the algorithm permanently**.
Re-tuning the scorer never silently undoes a decision a person made.

An LLM may suggest, but the ledger records what a HUMAN decided. The suggestion
is kept alongside in `suggested_by`/`suggested_score`, so the provenance of a
merge is never lost -- you can always ask "who decided this, and what did the
machine think at the time?"

Columns:
    pair_id         stable id for the unordered pair of keys
    left_key        normalized key, lexicographically first
    right_key       normalized key, second
    decision        same | different
    decided_by      a person's name or handle -- never a model
    decided_on      ISO date
    suggested_by    what proposed it: "auto", "review", or a model name
    suggested_score the score at the time of the decision
    note            free text; why
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# Column names follow docs/ENTITY_RESOLUTION.md so the file is the one that
# spec describes. pair_id, suggested_by and suggested_score are additions, not
# departures: CLAUDE.md requires that anything a model touched stay traceable,
# and keeping the suggestion beside the human decision is how that is done.
LEDGER_COLUMNS = [
    "pair_id",
    "name_key_a",
    "name_key_b",
    "decision",
    "decided_by",
    "decided_at",
    "suggested_by",
    "suggested_score",
    "note",
]

SAME = "same"
DIFFERENT = "different"


def pair_id(left: str, right: str) -> str:
    """Stable id for an unordered pair, so order never creates a duplicate."""
    first, second = sorted((left, right))
    digest = hashlib.sha256(f"{first}\x00{second}".encode("utf-8")).hexdigest()
    return digest[:16]


@dataclass
class Resolution:
    left_key: str
    right_key: str
    decision: str
    decided_by: str
    decided_on: str = ""
    suggested_by: str = ""
    suggested_score: str = ""
    note: str = ""

    def __post_init__(self):
        self.left_key, self.right_key = sorted((self.left_key, self.right_key))
        if not self.decided_on:
            self.decided_on = date.today().isoformat()
        if self.decision not in (SAME, DIFFERENT):
            raise ValueError(f"decision must be {SAME!r} or {DIFFERENT!r}, got {self.decision!r}")
        if not self.decided_by:
            raise ValueError("decided_by is required -- a decision needs an owner")

    @property
    def pair_id(self) -> str:
        return pair_id(self.left_key, self.right_key)

    def as_row(self) -> dict:
        return {
            "pair_id": self.pair_id,
            "name_key_a": self.left_key,
            "name_key_b": self.right_key,
            "decision": self.decision,
            "decided_by": self.decided_by,
            "decided_at": self.decided_on,
            "suggested_by": self.suggested_by,
            "suggested_score": self.suggested_score,
            "note": self.note,
        }


class Ledger:
    """Loaded resolutions, queryable by pair."""

    def __init__(self, resolutions=None):
        self._by_pair = {}
        for resolution in resolutions or []:
            self._by_pair[resolution.pair_id] = resolution

    def __len__(self) -> int:
        return len(self._by_pair)

    def decision_for(self, left: str, right: str):
        """'same', 'different', or None if no human has ruled on this pair."""
        resolution = self._by_pair.get(pair_id(left, right))
        return resolution.decision if resolution else None

    def add(self, resolution: Resolution) -> None:
        self._by_pair[resolution.pair_id] = resolution

    def apply(self, match):
        """Override a machine decision with the human one, where one exists.

        Returns the match unchanged when the ledger is silent, so an untouched
        pair keeps flowing through the normal bands.
        """
        ruling = self.decision_for(match.left, match.right)
        if ruling is None:
            return match
        match.decision = "accepted" if ruling == SAME else "rejected"
        match.reason = f"human decision on record ({ruling}); " + match.reason
        return match

    @classmethod
    def load(cls, path: Path):
        if not Path(path).exists():
            return cls()
        with Path(path).open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        return cls(
            Resolution(
                left_key=r["name_key_a"],
                right_key=r["name_key_b"],
                decision=r["decision"],
                decided_by=r["decided_by"],
                decided_on=r.get("decided_at", ""),
                suggested_by=r.get("suggested_by", ""),
                suggested_score=r.get("suggested_score", ""),
                note=r.get("note", ""),
            )
            for r in rows
        )

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=LEDGER_COLUMNS)
            writer.writeheader()
            for resolution in sorted(self._by_pair.values(), key=lambda r: r.left_key):
                writer.writerow(resolution.as_row())


class UnionFind:
    """Groups accepted pairs into one canonical entity each."""

    def __init__(self):
        self.parent = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            # Lexicographically smallest root keeps entity ids stable across
            # runs, so a published entity URL does not change when data grows.
            root, child = sorted((left_root, right_root))
            self.parent[child] = root

    def groups(self):
        clusters = {}
        for item in self.parent:
            clusters.setdefault(self.find(item), set()).add(item)
        return clusters
