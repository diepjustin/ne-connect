import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "build"))

from vendor_donor_join import MIN_STRONG_KEY_LENGTH, match_tier  # noqa: E402


def test_organization_pairs_are_strong():
    assert match_tier("UNION PACIFIC RAILROAD", {"organization"}, {"organization"}) == "strong"


def test_any_individual_makes_it_weak():
    """A person's key is LAST FIRST and collides freely, so it never counts."""
    assert match_tier("SMITH JOHN", {"organization"}, {"individual"}) == "weak"
    assert match_tier("SMITH JOHN", {"individual"}, {"organization"}) == "weak"


def test_short_or_single_token_keys_are_weak():
    # "ACE" or "K C" match by coincidence, not identity.
    assert match_tier("ACE", {"organization"}, {"organization"}) == "weak"
    assert match_tier("SANDHILLS", {"organization"}, {"organization"}) == "weak"
    assert len("SANDHILLS") >= MIN_STRONG_KEY_LENGTH  # demoted for token count, not length


def test_two_token_long_key_is_strong():
    assert match_tier("HAWKINS CONSTRUCTION", {"organization"}, {"organization"}) == "strong"
