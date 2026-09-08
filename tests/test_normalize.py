import pytest
from normalize import NormalizedName, normalize_org, normalize_person


def key(name):
    return normalize_org(name).key


def test_the_four_spellings_of_one_real_vendor():
    """From ne-contracts: one roofing company, four vendor strings."""
    assert key("10 MEN") == "10 MEN"
    assert key("10 MEN 14654") == "10 MEN"
    assert key("10 MEN LLC") == "10 MEN"


def test_dba_concatenation_is_not_yet_solved():
    # "10 MEN LLC 10 MEN ROOFING" is a name plus a DBA glued together. The LLC
    # sits mid-string, so trailing-suffix stripping leaves it alone and the key
    # does NOT collapse to "10 MEN". Pretending otherwise would be exactly the
    # silent merge this project refuses to make. Left for the fuzzy phase.
    assert key("10 MEN LLC 10 MEN ROOFING") == "10 MEN LLC 10 MEN ROOFING"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Ameritas Life Insurance Corp.", "AMERITAS LIFE INSURANCE"),
        ("AMERITAS LIFE INS", "AMERITAS LIFE INSURANCE"),
        ("Smith Construction Co Inc", "SMITH CONSTRUCTION"),
        ("The Buckle, Inc.", "BUCKLE"),
        ("Johnson & Johnson", "JOHNSON AND JOHNSON"),
        ("ACME SVCS LLC", "ACME SERVICES"),
        ("First Natl Bank", "FIRST NATIONAL BANK"),
    ],
)
def test_org_normalization(raw, expected):
    assert key(raw) == expected


def test_nebraska_aliases():
    assert key("NPPD") == "NEBRASKA PUBLIC POWER DISTRICT"
    assert key("OPPD") == "OMAHA PUBLIC POWER DISTRICT"
    assert key("Board of Regents") == "UNIVERSITY OF NEBRASKA"
    assert key("UNL") == "UNIVERSITY OF NEBRASKA LINCOLN"


def test_suffix_stripping_never_empties_the_key():
    # "CO INC" is all suffix. If it normalized to "" it would match every other
    # all-suffix string, silently merging unrelated vendors.
    assert key("CO INC") == "CO"
    assert key("LLC") == "LLC"


def test_rules_are_recorded_for_show_your_work():
    result = normalize_org("The Buckle, Inc.")
    assert result.key == "BUCKLE"
    assert result.original == "The Buckle, Inc."
    assert "stripped punctuation" in result.rules
    assert "dropped leading THE" in result.rules
    assert any("legal suffix" in r for r in result.rules)


def test_empty_name_is_falsy():
    assert not normalize_org("")
    assert not normalize_org("   ")
    assert isinstance(normalize_org(""), NormalizedName)


def test_small_trailing_numbers_survive():
    # Only 3+ digit runs look like account numbers.
    assert key("PHASE 2") == "PHASE 2"
    assert key("VENDOR 14654") == "VENDOR"


def test_person_key_is_last_first():
    assert normalize_person("Smith", "John", "Q", "Jr").key == "SMITH JOHN"
    assert normalize_person("O'Brien", "Mary").key == "O BRIEN MARY"


def test_person_key_deliberately_collides():
    """Two different John Smiths produce one key. That is the point.

    The key is weak by design; callers must corroborate with city/zip/employer
    before calling it a match.
    """
    a = normalize_person("Smith", "John", "Adam")
    b = normalize_person("Smith", "John", "Bernard")
    assert a.key == b.key == "SMITH JOHN"
    assert "dropped middle name/suffix" in a.rules
