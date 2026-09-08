"""Record a human decision into resolve/resolutions.csv.

The review loop's write path. Decisions are permanent and override the scorer
forever after, so this refuses to run without a named person: `--by` is not
optional, and it may not be a model. An LLM's opinion belongs in --suggested-by,
never in --by.

    python build/review.py --same "MOLINA HEALTHCARE" "MOLINA HEALTHCARE OF NEBRASKA" \
        --by jdiep --note "parent and its Nebraska subsidiary"

    python build/review.py --different "J P MORGAN SECURITIES" "P J MORGAN" \
        --by jdiep --note "Wall Street bank vs unrelated Omaha real estate firm"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "resolve"))

from resolutions import DIFFERENT, SAME, Ledger, Resolution  # noqa: E402

LEDGER_PATH = ROOT / "data" / "manual" / "resolutions.csv"

# Anything that looks like a model name is rejected as a decision owner. The
# ledger's whole value is that a person stands behind each row.
MODEL_HINTS = ("gpt", "claude", "llm", "ai", "model", "bot", "auto")


def record(left, right, decision, by, note="", suggested_by="", suggested_score="",
           ledger_path=None):
    path = Path(ledger_path or LEDGER_PATH)
    if any(hint in by.lower() for hint in MODEL_HINTS):
        raise ValueError(
            f"--by must name a person, got {by!r}. A model may suggest "
            "(--suggested-by), but only a human decides."
        )
    ledger = Ledger.load(path)
    ledger.add(
        Resolution(
            left_key=left,
            right_key=right,
            decision=decision,
            decided_by=by,
            note=note,
            suggested_by=suggested_by,
            suggested_score=suggested_score,
        )
    )
    ledger.save(path)
    return ledger


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--same", nargs=2, metavar=("LEFT", "RIGHT"))
    group.add_argument("--different", nargs=2, metavar=("LEFT", "RIGHT"))
    parser.add_argument("--by", required=True, help="the person deciding (not a model)")
    parser.add_argument("--note", default="", help="why -- this is the useful part")
    parser.add_argument("--suggested-by", default="")
    parser.add_argument("--suggested-score", default="")
    args = parser.parse_args(argv)

    left, right = args.same or args.different
    decision = SAME if args.same else DIFFERENT
    try:
        ledger = record(
            left, right, decision, args.by, args.note, args.suggested_by, args.suggested_score
        )
    except ValueError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    print(f"recorded: {left!r} {decision} {right!r} (by {args.by})")
    print(f"ledger now holds {len(ledger)} decision(s); re-run build/build_entities.py to apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
