"""Flag a sibling data release that has quietly gone stale.

build/verify_payload.py catches a build that is *empty or broken*. This
script catches the other unattended failure mode: a sibling scraper that
died weeks ago while ne-connect kept rebuilding, green every night, from the
same old release. The page already states each source's retrieval date
honestly (build_site.py's retrieval_dates()), so this is the *operator's*
alarm, not the reader's -- it runs in ne-connect-nightly.yml's own
`freshness` job, which fails red on its own without blocking `deploy`.
Three fresh sources should still ship even when the fourth has stalled.

Every sibling's hub-data release tag ends in the America/Chicago date it was
cut (`ne-contracts-hub-data-2026-09-20`, `lobbying-data-2026-09-14`, ...),
which is the only reliable publish date -- the GitHub API's `created_at` on
a release is the date of the *commit* it points at, not when it was
published (checked directly 2026-09-20).

Thresholds are each sibling's cadence plus slack: the runner compares in
UTC against a Central-time tag date, a scheduled run can slip hours, and one
missed night is a warning, not an outage.

Usage:
    python build/check_freshness.py --tag contracts=ne-contracts-hub-data-2026-09-20 \\
        --tag campaign_finance=... --tag lobbying=... --tag fec=... [--today YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date

# source -> (warn after N days, fail after N days). The first number is
# "one or two runs missed"; the second is "something is actually broken".
CADENCES = {
    "contracts": (3, 7),          # ne-contracts/daily.yml: nightly
    "campaign_finance": (3, 7),   # ne-campaign-finance/daily.yml: nightly
    "fec": (10, 21),              # ne-fec/ne-fec-weekly.yml: Sundays
    "lobbying": (40, 70),         # ne-lobbying/daily.yml: monthly, on the 1st
}

_TAG_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})$")


def tag_date(tag: str) -> date | None:
    """The YYYY-MM-DD a release tag ends with, or None if it has none."""
    match = _TAG_DATE.search(tag or "")
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def check(tags: dict[str, str], today: date) -> tuple[list[str], list[str]]:
    """Returns (warnings, failures), each a list of human-readable lines.

    A source with no tag at all is a failure: the build just ran without
    that source entirely, which is worse than stale. A tag with no parseable
    date is a failure too -- it means the naming convention this check
    relies on has drifted, and a silent pass would hide that.
    """
    warnings: list[str] = []
    failures: list[str] = []
    for source, (warn_after, fail_after) in CADENCES.items():
        tag = (tags.get(source) or "").strip()
        if not tag:
            failures.append(f"{source}: no release found at all -- tonight's build has no {source} data")
            continue
        cut = tag_date(tag)
        if cut is None:
            failures.append(f"{source}: release tag {tag!r} has no YYYY-MM-DD suffix to date it by")
            continue
        age = max(0, (today - cut).days)
        if age > fail_after:
            failures.append(
                f"{source}: newest release {tag} is {age} days old "
                f"(cadence allows {fail_after}) -- its scraper has probably stopped publishing"
            )
        elif age > warn_after:
            warnings.append(
                f"{source}: newest release {tag} is {age} days old "
                f"(expected within {warn_after}) -- one or more runs missed"
            )
    return warnings, failures


def _parse_tag_args(pairs: list[str]) -> dict[str, str]:
    tags: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"--tag expects source=tag, got {pair!r}")
        source, _, tag = pair.partition("=")
        if source not in CADENCES:
            raise SystemExit(f"unknown source {source!r}; known: {', '.join(CADENCES)}")
        tags[source] = tag
    return tags


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tag", action="append", default=[], metavar="SOURCE=TAG",
                        help="a sibling's newest hub-data release tag (repeatable)")
    parser.add_argument("--today", type=date.fromisoformat, default=None,
                        help="override the comparison date (tests)")
    args = parser.parse_args(argv)

    tags = _parse_tag_args(args.tag)
    today = args.today or date.today()
    warnings, failures = check(tags, today)

    for source in CADENCES:
        print(f"  {source:18} {tags.get(source) or '(none)'}")
    for line in warnings:
        print(f"::warning::{line}")
    for line in failures:
        print(f"::error::{line}", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} source(s) stale or missing -- see the annotations above", file=sys.stderr)
        return 1
    print("\nevery sibling release is within its cadence" + (" (with warnings)" if warnings else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
