"""Deterministic name normalization.

Pure functions. Same input, same output, forever. No network, no model, no
randomness. Everything downstream depends on this being stable, because
`name_key` values are baked into published entity IDs.

See docs/ENTITY_RESOLUTION.md for the policy this implements.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

try:
    import yaml
except ImportError:  # aliases are optional at import time
    yaml = None

ALIASES_PATH = Path(__file__).parent / "aliases.yml"

# Legal suffixes stripped from organization names. Order matters only in that
# longer forms are tried first (handled by sorting at use site).
LEGAL_SUFFIXES = {
    "INC", "INCORPORATED", "LLC", "L L C", "LLP", "LP", "LC", "PLLC", "PC",
    "CO", "CORP", "CORPORATION", "COMPANY", "LTD", "LIMITED",
    "ASSOCIATION", "PARTNERSHIP", "TRUST", "HOLDINGS",
}

# Expanded so that abbreviated and spelled-out forms collide.
ABBREVIATIONS = {
    "INS": "INSURANCE",
    # ASSOC/ASSOCIATES is a firm name ("Olsson Associates"); ASSN/ASSOCIATION is a
    # legal suffix stripped below. Expanding first keeps the two from colliding.
    "ASSOC": "ASSOCIATES",
    "ASSOCS": "ASSOCIATES",
    "ASSN": "ASSOCIATION",
    "MFG": "MANUFACTURING",
    "MFRS": "MANUFACTURERS",
    "CONSTR": "CONSTRUCTION",
    "CONST": "CONSTRUCTION",
    "SVC": "SERVICES",
    "SVCS": "SERVICES",
    "SERV": "SERVICES",
    "SERVICE": "SERVICES",
    "TECH": "TECHNOLOGY",
    "TECHS": "TECHNOLOGY",
    "NATL": "NATIONAL",
    "NATIONWIDE": "NATIONWIDE",
    "MGMT": "MANAGEMENT",
    "MGT": "MANAGEMENT",
    "ENG": "ENGINEERING",
    "ENGR": "ENGINEERING",
    "DIST": "DISTRICT",
    "CNTY": "COUNTY",
    "CTY": "COUNTY",
    "DEPT": "DEPARTMENT",
    "DEPARTMENT": "DEPARTMENT",
    "UNIV": "UNIVERSITY",
    "SYS": "SYSTEM",
    "INTL": "INTERNATIONAL",
    "INT": "INTERNATIONAL",
    "BROS": "BROTHERS",
    "MED": "MEDICAL",
    "CTR": "CENTER",
    "CENTRE": "CENTER",
    "HOSP": "HOSPITAL",
    "PROF": "PROFESSIONAL",
    "SOLNS": "SOLUTIONS",
    "GRP": "GROUP",
    "TRANSP": "TRANSPORTATION",
    "EQUIP": "EQUIPMENT",
    "ELEC": "ELECTRIC",
    "AGRI": "AGRICULTURAL",
    "AG": "AGRICULTURAL",
    "NE": "NEBRASKA",
    "NEBR": "NEBRASKA",
}

PERSON_TITLES = {
    "MR", "MRS", "MS", "MISS", "DR", "PROF", "SEN", "SENATOR", "REP",
    "REPRESENTATIVE", "HON", "HONORABLE", "GOV", "GOVERNOR", "JUDGE",
}

PERSON_SUFFIXES = {"JR", "SR", "II", "III", "IV", "V", "MD", "DDS", "PHD", "ESQ", "CPA"}

NICKNAMES = {
    "BOB": "ROBERT", "BOBBY": "ROBERT", "ROB": "ROBERT",
    "BILL": "WILLIAM", "BILLY": "WILLIAM", "WILL": "WILLIAM",
    "DICK": "RICHARD", "RICK": "RICHARD", "RICH": "RICHARD",
    "JIM": "JAMES", "JIMMY": "JAMES",
    "JOE": "JOSEPH", "JOEY": "JOSEPH",
    "MIKE": "MICHAEL", "MICK": "MICHAEL",
    "TOM": "THOMAS", "TOMMY": "THOMAS",
    "DAVE": "DAVID",
    "STEVE": "STEPHEN", "STEVEN": "STEPHEN",
    "CHRIS": "CHRISTOPHER",
    "DAN": "DANIEL", "DANNY": "DANIEL",
    "TONY": "ANTHONY",
    "TED": "EDWARD", "NED": "EDWARD", "EDDIE": "EDWARD", "ED": "EDWARD",
    "KEN": "KENNETH",
    "LARRY": "LAWRENCE",
    "JEFF": "JEFFREY",
    "GREG": "GREGORY",
    "PAT": "PATRICK",
    "SUE": "SUSAN", "SUSIE": "SUSAN",
    "BETH": "ELIZABETH", "LIZ": "ELIZABETH", "BETTY": "ELIZABETH",
    "KATHY": "KATHERINE", "KATE": "KATHERINE", "KATIE": "KATHERINE",
    "PEGGY": "MARGARET", "MEG": "MARGARET", "MAGGIE": "MARGARET",
    "NANCY": "ANN", "NAN": "ANN",
    "JENNY": "JENNIFER", "JEN": "JENNIFER",
    "DEB": "DEBORAH", "DEBBIE": "DEBORAH",
    "CINDY": "CYNTHIA",
    "SANDY": "SANDRA",
    "BARB": "BARBARA",
}

_PUNCT_KEEP_AMP = re.compile(r"[^\w&\s]", re.UNICODE)
_WS = re.compile(r"\s+")
# A trailing account number, or a decimal contract reference: the state
# publishes both, and "KIEWIT BUILDING GROUP, INC. 4.12788" stayed a separate
# entity from "KIEWIT BUILDING GROUP INC" until the decimal form was covered.
_TRAILING_REF = re.compile(r"\s+(\d{3,}|\d+\.\d{3,})$")
# Same bookkeeping noise at the front: 205 vendor strings look like
# "10084 CROUCH RECREATION". Leading refs cost matches rather than inventing
# them, but they are just as removable.
_LEADING_REF = re.compile(r"^\d{4,}\s+")
_DBA = re.compile(r"\b(D\s*/?\s*B\s*/?\s*A|DBA|DOING BUSINESS AS)\b")
# The slash is REQUIRED. With it optional this also matched the bare token
# "CO" -- an extremely common company suffix -- and truncated everything after
# it. Against 60,000 real vendor strings that mangled 236 names and collapsed
# "AMERICAN FENCE CO OF LINCOLN", "AMERICAN FENCE CO OF KEARNEY" and "AMER
# FENCE CO OF SOUTH DAKOTA" onto one key: three companies in three cities
# merged into one entity, which is the exact false-match ENTITY_RESOLUTION.md
# calls the worst possible failure.
_CO_ATTN = re.compile(r"\b(C\s*/\s*O|ATTN|ATTENTION)\b.*$")


@lru_cache(maxsize=1)
def _load_aliases() -> dict[str, str]:
    """Nebraska-specific alias map, normalized-key -> canonical normalized key."""
    if yaml is None or not ALIASES_PATH.exists():
        return {}
    raw = yaml.safe_load(ALIASES_PATH.read_text()) or {}
    out: dict[str, str] = {}
    for canonical, entry in raw.get("organizations", {}).items():
        canon_key = _core_org(canonical)
        for variant in entry.get("aliases", []):
            out[_core_org(variant)] = canon_key
        out[canon_key] = canon_key
    return out


def _strip_accents(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )


def _core_org(name: str) -> str:
    """Normalization without the alias lookup — used to build the alias map itself."""
    if not name:
        return ""
    s = _strip_accents(name).upper()
    s = _CO_ATTN.sub(" ", s)
    s = s.replace("&", " AND ")

    # Before punctuation folding, while a decimal reference is still one token:
    # fold "4.12788" first and it becomes "4 12788", of which only the tail
    # looks like a reference, leaving a stray "4" that then blocks the legal
    # suffix strip below.
    s = _LEADING_REF.sub("", s)
    s = _TRAILING_REF.sub("", s.rstrip())

    s = _PUNCT_KEEP_AMP.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    # Again, now that punctuation is gone: "SMITH CO. #14654" only exposes its
    # reference once the "#" has been folded away.
    s = _TRAILING_REF.sub("", s).strip()

    # Strip a trailing account/reference number BEFORE suffix handling. The
    # state's contract vendor strings carry them -- one roofing company appears
    # as "10 MEN", "10 MEN LLC" and "10 MEN 14654" across 60,000 vendor names --
    # and leaving one attached also blocks the suffix strip below, so
    # "CONSOLIDATED COMPANIES, INC. 24641" would keep its INC as well.
    # Three digits or more, so a name genuinely ending in a small number
    # ("PHASE 2", "PIER 1") survives.
    tokens = [ABBREVIATIONS.get(t, t) for t in s.split()]
    # Strip legal suffixes from the tail only; "CORPORATION FOR PUBLIC
    # BROADCASTING" must keep its leading CORPORATION.
    while len(tokens) > 1 and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    # "THE" carries no signal in either position.
    if tokens and tokens[0] == "THE":
        tokens = tokens[1:]
    return " ".join(tokens)


def split_dba(name: str) -> list[str]:
    """Return each side of a d/b/a as its own candidate name."""
    if not name:
        return []
    upper = _strip_accents(name).upper()
    if _DBA.search(upper):
        parts = _DBA.split(upper)
        return [p.strip() for p in parts if p.strip() and not _DBA.fullmatch(p.strip())]
    return [name]


def normalize_org(name: str | None) -> str:
    """Normalized key for an organization name.

    >>> normalize_org("Ameritas Life Insurance Corp.")
    'AMERITAS LIFE INSURANCE'
    >>> normalize_org("AMERITAS LIFE INS")
    'AMERITAS LIFE INSURANCE'
    """
    if not name:
        return ""
    core = _core_org(name)
    return _load_aliases().get(core, core)


@dataclass(frozen=True)
class PersonName:
    last: str = ""
    first: str = ""
    middle: str = ""
    suffix: str = ""
    raw: str = ""

    @property
    def key(self) -> str:
        """Full comparison key."""
        parts = [self.last, self.first, self.middle]
        return "|".join(p for p in parts if p)

    @property
    def block_key(self) -> str:
        """Cheap blocking key: last name + first initial."""
        if not self.last:
            return ""
        initial = self.first[:1] if self.first else ""
        return f"{self.last}|{initial}"


def normalize_person(name: str | None) -> PersonName:
    """Parse a person name into components.

    Handles both "LAST, FIRST M" and "FIRST M LAST" orderings.

    >>> normalize_person("Smith, Robert J. Jr.").key
    'SMITH|ROBERT|J'
    >>> normalize_person("Bob Smith").block_key
    'SMITH|R'
    """
    if not name:
        return PersonName(raw=name or "")
    raw = name
    s = _strip_accents(name).upper()
    s = _CO_ATTN.sub(" ", s)
    s = re.sub(r"[^\w,\s]", " ", s)
    s = _WS.sub(" ", s).strip()

    comma_first = "," in s
    tokens = [t for t in re.split(r"[,\s]+", s) if t]
    tokens = [t for t in tokens if t not in PERSON_TITLES]

    suffix = ""
    while tokens and tokens[-1] in PERSON_SUFFIXES:
        suffix = tokens.pop()

    if not tokens:
        return PersonName(suffix=suffix, raw=raw)

    if comma_first:
        last, rest = tokens[0], tokens[1:]
    else:
        last, rest = tokens[-1], tokens[:-1]

    first = rest[0] if rest else ""
    middle = " ".join(rest[1:]) if len(rest) > 1 else ""
    first = NICKNAMES.get(first, first)

    return PersonName(
        last=last, first=first, middle=middle, suffix=suffix, raw=raw
    )


ORG_SIGNALS = LEGAL_SUFFIXES | set(ABBREVIATIONS) | set(ABBREVIATIONS.values()) | {
    "DEPARTMENT", "UNIVERSITY", "DISTRICT", "COUNTY", "CITY", "STATE", "SCHOOL",
    "BOARD", "COMMISSION", "FUND", "PAC", "COMMITTEE", "FOUNDATION", "CHURCH",
    "UNION", "BANK", "ENERGY", "SOLUTIONS", "SYSTEMS", "ENTERPRISES", "PARTNERS",
    "PROPERTIES", "INDUSTRIES", "FARMS", "RANCH", "SUPPLY", "MOTORS", "REALTY",
    "CLINIC", "HEALTH", "CAPITAL", "INVESTMENTS", "CONSULTING", "LOGISTICS",
    "LIFE", "MUTUAL", "FEDERAL", "AMERICAN", "MIDWEST", "GREAT", "PLAINS",
}


def looks_like_person(name: str | None) -> bool:
    """Heuristic gate: is this string a person or an organization?

    Deliberately conservative. When unsure it returns False, because in this
    pipeline a person mis-filed as an org still matches on name; an org mis-filed
    as a person gets a person block key and silently stops matching anything.

    A `force_kind` argument exists on `normalize()` for sources where the field
    is known — always prefer that over this guess when the source tells you.
    """
    if not name:
        return False
    upper = _strip_accents(name).upper()
    tokens = [t for t in re.split(r"[^\w]+", upper) if t]
    if not tokens:
        return False
    if set(tokens) & ORG_SIGNALS:
        return False

    meaningful = [t for t in tokens if t not in PERSON_TITLES and t not in PERSON_SUFFIXES]
    if not meaningful:
        return False

    # "Smith, Robert J." — the comma ordering is a strong person signal.
    if "," in name and len(meaningful) <= 4:
        return True
    # "Robert Smith"
    if len(meaningful) == 2:
        return True
    # "Joseph D. Kohout" — a bare middle initial is the giveaway.
    if len(meaningful) == 3 and any(len(t) == 1 for t in meaningful[1:-1]):
        return True
    return False


@dataclass
class NormalizedName:
    """What every scraper attaches to a name field."""

    raw: str
    key: str
    kind: str  # "org" or "person"
    person: PersonName | None = None
    candidates: list[str] = field(default_factory=list)


def normalize(name: str | None, force_kind: str | None = None) -> NormalizedName:
    """Front door. Routes to org or person normalization."""
    raw = name or ""
    kind = force_kind or ("person" if looks_like_person(raw) else "org")
    if kind == "person":
        parsed = normalize_person(raw)
        return NormalizedName(raw=raw, key=parsed.key, kind="person", person=parsed)
    candidates = [normalize_org(part) for part in split_dba(raw)]
    candidates = [c for c in candidates if c]
    return NormalizedName(
        raw=raw,
        key=candidates[0] if candidates else "",
        kind="org",
        candidates=candidates,
    )
