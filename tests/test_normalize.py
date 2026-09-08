"""Tests for name normalization.

These are the guard rails on the most important module in the repo. When adding a
normalization rule, add a case here first. When a real-world mismatch is found in
the data, add it here before fixing it.
"""

import pytest

from resolve.normalize import (
    looks_like_person,
    normalize,
    normalize_org,
    normalize_person,
    split_dba,
)


class TestOrgNormalization:
    @pytest.mark.parametrize(
        "a,b",
        [
            ("Ameritas Life Insurance Corp.", "AMERITAS LIFE INS"),
            ("Kiewit Corporation", "KIEWIT CORP"),
            ("Union Pacific Railroad Co", "Union Pacific Railroad Company"),
            ("Werner Enterprises, Inc.", "WERNER ENTERPRISES INC"),
            ("Olsson Associates", "Olsson Assoc"),
            ("HDR Engineering, Inc.", "HDR Engr Inc"),
            ("Black Hills Energy", "BLACK HILLS ENERGY"),
            ("The Weitz Company LLC", "Weitz Company"),
            ("Cargill Meat Solutions Corp", "CARGILL MEAT SOLNS CORP"),
            ("Nebraska Beef, Ltd.", "NEBRASKA BEEF LTD"),
        ],
    )
    def test_variants_collide(self, a, b):
        assert normalize_org(a) == normalize_org(b)

    @pytest.mark.parametrize(
        "a,b",
        [
            ("Johnson Construction", "Johnson Construction of Omaha"),
            ("Sandhills Holdings II", "Sandhills Holdings III"),
            ("First National Bank", "First National Insurance"),
            ("Lincoln Industries", "Lincoln Industrial Supply"),
        ],
    )
    def test_distinct_names_stay_distinct(self, a, b):
        assert normalize_org(a) != normalize_org(b)

    def test_ampersand_folds_to_and(self):
        assert normalize_org("Smith & Jones") == normalize_org("Smith and Jones")

    def test_leading_the_dropped(self):
        assert normalize_org("The Buckle") == normalize_org("Buckle")

    def test_leading_corporation_kept(self):
        # Tail-only suffix stripping: a leading "Corporation" is part of the name.
        assert "CORPORATION" in normalize_org("Corporation for Public Broadcasting")

    def test_care_of_stripped(self):
        assert normalize_org("Genentech Inc c/o 2350 Kerner Blvd") == normalize_org(
            "Genentech, Inc."
        )

    def test_empty_input(self):
        assert normalize_org(None) == ""
        assert normalize_org("") == ""

    def test_deterministic(self):
        name = "Ameritas Life Insurance Corp."
        assert normalize_org(name) == normalize_org(name)


class TestNebraskaAliases:
    """Requires resolve/aliases.yml and PyYAML."""

    @pytest.mark.parametrize(
        "a,b",
        [
            ("NPPD", "Nebraska Public Power District"),
            ("OPPD", "Omaha Public Power District"),
            ("NDOR", "Nebraska Department of Transportation"),
            ("Nebraska Department of Roads", "NDOT"),
            ("NDEQ", "Nebraska Department of Environment and Energy"),
            ("DHHS", "Nebraska Department of Health and Human Services"),
            ("UNL", "University of Nebraska-Lincoln"),
        ],
    )
    def test_alias_pairs(self, a, b):
        pytest.importorskip("yaml")
        assert normalize_org(a) == normalize_org(b)

    def test_campuses_stay_separate(self):
        """Reporters need to know which campus. Do not collapse into the Regents."""
        pytest.importorskip("yaml")
        assert normalize_org("UNL") != normalize_org("UNO")
        assert normalize_org("UNL") != normalize_org("University of Nebraska")

    def test_unmc_not_nebraska_medicine(self):
        """Different legal entities; conflating them would be a factual error."""
        pytest.importorskip("yaml")
        assert normalize_org("UNMC") != normalize_org("Nebraska Medicine")


class TestDba:
    def test_splits_both_sides(self):
        parts = split_dba("Acme Holdings LLC d/b/a Cornhusker Catering")
        assert len(parts) == 2

    def test_passthrough_when_absent(self):
        assert split_dba("Acme Holdings LLC") == ["Acme Holdings LLC"]

    def test_normalize_keeps_both_candidates(self):
        result = normalize("Acme Holdings LLC dba Cornhusker Catering")
        assert len(result.candidates) == 2


class TestPersonNormalization:
    def test_comma_ordering(self):
        p = normalize_person("Smith, Robert J. Jr.")
        assert p.last == "SMITH"
        assert p.first == "ROBERT"
        assert p.middle == "J"
        assert p.suffix == "JR"

    def test_natural_ordering(self):
        p = normalize_person("Robert J Smith")
        assert p.last == "SMITH"
        assert p.first == "ROBERT"

    def test_orderings_agree(self):
        assert normalize_person("Smith, Robert J").key == normalize_person(
            "Robert J Smith"
        ).key

    def test_nickname_expansion(self):
        assert normalize_person("Bob Smith").first == "ROBERT"
        assert normalize_person("Bill Kohout").first == "WILLIAM"

    def test_title_stripped(self):
        assert normalize_person("Sen. John Doe").last == "DOE"

    def test_block_key_uses_initial(self):
        assert normalize_person("Robert Smith").block_key == "SMITH|R"
        assert normalize_person("Bob Smith").block_key == "SMITH|R"

    def test_empty(self):
        assert normalize_person(None).key == ""


class TestKindDetection:
    @pytest.mark.parametrize(
        "name",
        [
            "Nebraska Public Power District",
            "Kiewit Corporation",
            "Lancaster County Agricultural Society, Inc.",
            "Nebraskans for Good Government PAC",
            "First National Bank",
        ],
    )
    def test_orgs_detected(self, name):
        assert looks_like_person(name) is False

    @pytest.mark.parametrize(
        "name",
        ["Smith, Robert J.", "Joseph D. Kohout", "Ann L. Parr"],
    )
    def test_people_detected(self, name):
        assert looks_like_person(name) is True

    def test_routing(self):
        assert normalize("Kiewit Corporation").kind == "org"
        assert normalize("Smith, Robert J.").kind == "person"

    def test_force_kind_overrides(self):
        assert normalize("Kiewit Corporation", force_kind="person").kind == "person"


class TestRegressions:
    """Add a case here every time a real mismatch is found in the data.

    Format: a one-line comment naming where it was seen, then the assertion.
    """

    def test_placeholder(self):
        # Delete this once the first real regression is recorded.
        assert True


# --- rules added from real Nebraska contract data -------------------------
# The spec was written before anyone had run the normalizer over the state's
# 60,000 vendor strings. These three cases come from that corpus.


def test_trailing_account_number_is_stripped():
    """One roofing company, three spellings, one of them with an account ref."""
    assert normalize_org("10 MEN") == normalize_org("10 MEN LLC") == normalize_org("10 MEN 14654")


def test_trailing_reference_does_not_block_suffix_stripping():
    # With the number attached, the tail is no longer a legal suffix, so INC
    # survived and the key became "CONSOLIDATED COMPANIES INC 24641".
    assert normalize_org("CONSOLIDATED COMPANIES, INC. 24641") == "CONSOLIDATED COMPANIES"


def test_leading_account_number_is_stripped():
    assert normalize_org("10084 CROUCH RECREATION") == normalize_org("Crouch Recreation")


def test_small_trailing_numbers_survive():
    """Only bookkeeping-sized runs go; a number that is part of the name stays."""
    assert normalize_org("PHASE 2") == "PHASE 2"
    assert normalize_org("PIER 1 IMPORTS") == "PIER 1 IMPORTS"


def test_bare_CO_does_not_truncate_the_name():
    """The c/o rule must not fire on the company suffix "CO".

    With the slash optional, these three collapsed onto one key -- three
    different companies in three different cities merged into one entity.
    """
    lincoln = normalize_org("AMERICAN FENCE CO OF LINCOLN")
    kearney = normalize_org("AMERICAN FENCE CO OF KEARNEY INC")
    assert lincoln != kearney
    assert "LINCOLN" in lincoln and "KEARNEY" in kearney


def test_real_c_o_is_still_stripped():
    assert normalize_org("Genentech Inc c/o 2350 Kerner Blvd") == normalize_org("Genentech")


def test_suffix_stripping_never_empties_a_key():
    # "CO INC" is all suffix; an empty key would match every other empty key.
    assert normalize_org("CO INC") == "CO"


def test_decimal_contract_reference_is_stripped():
    """The state appends decimal references as well as plain account numbers."""
    assert normalize_org("KIEWIT BUILDING GROUP, INC. 4.12788") == normalize_org(
        "KIEWIT BUILDING GROUP INC"
    )
    # A short decimal is not a reference and survives (punctuation still folds).
    assert normalize_org("VERSION 1.5") == "VERSION 1 5"
