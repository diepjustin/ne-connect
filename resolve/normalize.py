"""Deterministic name normalization.

Step 1 of the resolution pipeline in README.md. No fuzzy matching here -- this
turns a raw name string into a comparison key and, just as importantly, records
WHICH rules fired so every match can show its work.

The rules exist because the real data demands them. From ne-contracts' 60,000
distinct vendor strings, one vendor appears as all four of:

    10 MEN
    10 MEN 14654               <- trailing account number
    10 MEN LLC                 <- legal suffix
    10 MEN LLC 10 MEN ROOFING  <- name plus DBA, concatenated

Nothing here is clever, and that is deliberate: a normalization you cannot
explain to a reporter in one sentence is one you cannot publish behind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Stripped from the end, repeatedly -- "SMITH CONSTRUCTION CO INC" loses both.
LEGAL_SUFFIXES = {
    "INC",
    "INCORPORATED",
    "LLC",
    "LLP",
    "LP",
    "LTD",
    "LIMITED",
    "CORP",
    "CORPORATION",
    "CO",
    "COMPANY",
    "PC",
    "PLLC",
    "PA",
    "CHTD",
    "CHARTERED",
}

# Token-level expansions. Conservative on purpose: DIST is left alone because it
# is DISTRICT as often as DISTRIBUTING, and guessing wrong silently merges two
# real companies.
ABBREVIATIONS = {
    "INS": "INSURANCE",
    "MFG": "MANUFACTURING",
    "SVC": "SERVICES",
    "SVCS": "SERVICES",
    "SERV": "SERVICES",
    "SERVICE": "SERVICES",
    "ASSOC": "ASSOCIATION",
    "ASSN": "ASSOCIATION",
    "ASSOCIATES": "ASSOCIATION",
    "NATL": "NATIONAL",
    "NAT": "NATIONAL",
    "INTL": "INTERNATIONAL",
    "CTR": "CENTER",
    "CENTRE": "CENTER",
    "HOSP": "HOSPITAL",
    "UNIV": "UNIVERSITY",
    "DEPT": "DEPARTMENT",
    "MED": "MEDICAL",
    "EQUIP": "EQUIPMENT",
    "CONSTR": "CONSTRUCTION",
    "ELEC": "ELECTRIC",
    "BROS": "BROTHERS",
    "TRANSP": "TRANSPORTATION",
    "SYS": "SYSTEMS",
    "SYSTEM": "SYSTEMS",
    "MGMT": "MANAGEMENT",
    "MGT": "MANAGEMENT",
    "TECHNOLOGIES": "TECHNOLOGY",
    "SOLUTION": "SOLUTIONS",
    "ENTERPRISE": "ENTERPRISES",
}

# Whole-key rewrites applied after tokenization. Nebraska institutions appear
# under many names across sources and are high-volume enough that getting them
# wrong distorts any leaderboard.
NEBRASKA_ALIASES = {
    "NPPD": "NEBRASKA PUBLIC POWER DISTRICT",
    "OPPD": "OMAHA PUBLIC POWER DISTRICT",
    "MUD": "METROPOLITAN UTILITIES DISTRICT",
    "UNL": "UNIVERSITY OF NEBRASKA LINCOLN",
    "UNO": "UNIVERSITY OF NEBRASKA OMAHA",
    "UNK": "UNIVERSITY OF NEBRASKA KEARNEY",
    "UNMC": "UNIVERSITY OF NEBRASKA MEDICAL CENTER",
    "UNIVERSITY OF NEB": "UNIVERSITY OF NEBRASKA",
    "UNIVERSITY OF NEBR": "UNIVERSITY OF NEBRASKA",
    "BOARD OF REGENTS": "UNIVERSITY OF NEBRASKA",
    "BOARD OF REGENTS OF THE UNIVERSITY OF NEBRASKA": "UNIVERSITY OF NEBRASKA",
}

# Trailing account/reference numbers, e.g. "10 MEN 14654". Three digits or more
# so a real name ending in a small number ("PHASE 2") survives.
_TRAILING_NUMBER = re.compile(r"\s+\d{3,}$")
_NON_NAME_CHARS = re.compile(r"[^A-Z0-9&\s]")
_WHITESPACE = re.compile(r"\s+")


@dataclass
class NormalizedName:
    """A comparison key plus the audit trail that produced it."""

    key: str
    original: str
    rules: list = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.key)


def normalize_org(name: str) -> NormalizedName:
    """Organization name -> comparison key, recording every rule that fired."""
    original = name or ""
    rules = []
    text = original.upper().strip()

    if "&" in text:
        text = text.replace("&", " AND ")
        rules.append("expanded &")

    cleaned = _NON_NAME_CHARS.sub(" ", text)
    if cleaned != text:
        rules.append("stripped punctuation")
    text = _WHITESPACE.sub(" ", cleaned).strip()

    stripped = _TRAILING_NUMBER.sub("", text)
    if stripped != text:
        rules.append("removed trailing account number")
        text = stripped

    if text.startswith("THE "):
        text = text[4:]
        rules.append("dropped leading THE")

    tokens = text.split()
    expanded = [ABBREVIATIONS.get(t, t) for t in tokens]
    if expanded != tokens:
        rules.append("expanded abbreviations")
    tokens = expanded

    # Repeatedly, so "CO INC" loses both -- but never down to nothing, or
    # "CO INC" itself would normalize to the empty string and match everything.
    dropped = []
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        dropped.append(tokens.pop())
    if dropped:
        rules.append(f"dropped legal suffix {' '.join(reversed(dropped))}")

    key = " ".join(tokens)

    if key in NEBRASKA_ALIASES:
        key = NEBRASKA_ALIASES[key]
        rules.append("applied Nebraska alias")

    return NormalizedName(key=key, original=original, rules=rules)


def normalize_person(last: str, first: str, middle: str = "", suffix: str = "") -> NormalizedName:
    """Person name -> comparison key of LAST FIRST.

    Middle names and suffixes are dropped from the key because they are present
    in one source and absent in another far more often than they distinguish two
    real people. That makes the key deliberately WEAK: a person key is never
    enough on its own, and callers must corroborate with city, zip or employer
    before treating a hit as a match. See match_tier() in build/.
    """
    original = ", ".join(p for p in (last, first, middle, suffix) if p and p.strip())
    rules = []

    def clean(part):
        return _WHITESPACE.sub(" ", _NON_NAME_CHARS.sub(" ", (part or "").upper())).strip()

    last_c, first_c = clean(last), clean(first)
    if middle or suffix:
        rules.append("dropped middle name/suffix")

    key = " ".join(p for p in (last_c, first_c) if p)
    if key:
        rules.append("LAST FIRST key")
    return NormalizedName(key=key, original=original, rules=rules)
