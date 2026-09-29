"""_pairings() decides which two sources' keyed dicts get scored together.

Focused on the one behavior this module doesn't get elsewhere: fec_contributors
(individual itemized FEC donors) must pair against campaign_finance only, never
contracts/lobbying/disclosures -- those would only ever produce person-vs-
organization review-queue proposals with no auto-merge upside (match.py's
involves_person guard), and fec_contributors can run into the tens of thousands
of keys once indiv24.zip is pulled. fec_orgs (committees/candidates) keeps every
pairing the single merged "fec" dict used to have.
"""

from build_entities import _city_columns, _keyed_lobbying, _pairings
from sources import Party

VENDORS, CONTRIBUTORS, LOBBYING, DISCLOSURES = object(), object(), object(), object()
FEC_ORGS, FEC_CONTRIBUTORS = object(), object()


def _pairs():
    return _pairings(VENDORS, CONTRIBUTORS, LOBBYING, DISCLOSURES, FEC_ORGS, FEC_CONTRIBUTORS)


def test_fec_contributors_paired_only_against_campaign_finance():
    involving_fec_contributors = [
        p for p in _pairs() if FEC_CONTRIBUTORS in (p[1], p[3])
    ]
    assert len(involving_fec_contributors) == 1
    left_source, left_keyed, right_source, right_keyed = involving_fec_contributors[0]
    assert {left_keyed, right_keyed} == {CONTRIBUTORS, FEC_CONTRIBUTORS}
    assert {left_source, right_source} == {"campaign_finance", "fec"}


def test_fec_contributors_never_paired_against_contracts_lobbying_or_disclosures():
    for _, left_keyed, _, right_keyed in _pairs():
        if FEC_CONTRIBUTORS in (left_keyed, right_keyed):
            other = right_keyed if left_keyed is FEC_CONTRIBUTORS else left_keyed
            assert other not in (VENDORS, LOBBYING, DISCLOSURES)


def test_city_columns_joins_distinct_cities_from_both_sides():
    left = [Party(name="DOE, JANE", source="campaign_finance", role="contributor", cities={"OMAHA"})]
    right = [
        Party(name="DOE, JANE", source="fec", role="contributor", cities={"LINCOLN"}),
        Party(name="DOE, J.", source="fec", role="contributor", cities={"OMAHA"}),
    ]
    cols = _city_columns(left, right)
    assert cols["left_cities"] == "OMAHA"
    assert cols["right_cities"] == "LINCOLN | OMAHA"


def test_city_columns_empty_for_a_source_that_does_not_track_cities():
    """contracts/lobbying/disclosures Party objects never populate .cities --
    the review row must show an empty string, not crash or fabricate one."""
    left = [Party(name="ACME CO", source="contracts", role="vendor")]
    right = [Party(name="ACME COMPANY", source="lobbying", role="principal")]
    cols = _city_columns(left, right)
    assert cols["left_cities"] == ""
    assert cols["right_cities"] == ""


def test_fec_orgs_keeps_every_pairing_the_merged_fec_dict_used_to_have():
    involving_fec_orgs = {
        frozenset((left_keyed, right_keyed))
        for _, left_keyed, _, right_keyed in _pairs()
        if FEC_ORGS in (left_keyed, right_keyed)
    }
    assert involving_fec_orgs == {
        frozenset((VENDORS, FEC_ORGS)),
        frozenset((CONTRIBUTORS, FEC_ORGS)),
        frozenset((LOBBYING, FEC_ORGS)),
        frozenset((DISCLOSURES, FEC_ORGS)),
    }


def _principal(name="Nebraska Chamber of Commerce & Industry", records=4129, amount=1904311.14):
    return Party(
        name=name, source="lobbying", role="principal", entity_type="organization",
        record_count=records, total_amount=amount, source_id="1652",
    )


def _variants(keyed):
    return [variant for variants in keyed.values() for variant in variants]


def test_keyed_lobbying_counts_a_principal_once_across_alias_keys():
    """Every variant becomes its own canonical_entities.csv row and
    build_site.py sums every row, so the principal's totals must ride on one
    variant only. Copying them onto each spelling published 2x the Chamber's
    Form C total and position count on the live site."""
    keyed = _keyed_lobbying(
        {"1652": _principal()},
        {"1652": {"Nebraska Chamber of Commerce & Industry",
                  "Nebraska Chamber of Commerce & Indu..."}},
    )
    variants = _variants(keyed)
    assert len(keyed) == 2  # both spellings still reach the index
    assert sum(v.record_count for v in variants) == 4129
    assert round(sum(v.total_amount for v in variants), 2) == 1904311.14
    carrying = [v for v in variants if v.record_count]
    assert [v.name for v in carrying] == ["Nebraska Chamber of Commerce & Industry"]


def test_keyed_lobbying_counts_once_when_two_spellings_share_a_key():
    """Two raw spellings that normalize to the same key land in one list --
    the doubling happened there too."""
    keyed = _keyed_lobbying(
        {"1652": _principal()},
        {"1652": {"Nebraska Chamber of Commerce and Industry",
                  "NEBRASKA CHAMBER OF COMMERCE & INDUSTRY"}},
    )
    assert len(keyed) == 1
    variants = _variants(keyed)
    assert len(variants) == 3
    assert sum(v.record_count for v in variants) == 4129
    assert round(sum(v.total_amount for v in variants), 2) == 1904311.14


def test_keyed_lobbying_keeps_totals_when_the_principal_name_normalizes_to_nothing():
    keyed = _keyed_lobbying(
        {"1652": _principal(name="...")},
        {"1652": {"Nebraska Chamber of Commerce & Industry"}},
    )
    variants = _variants(keyed)
    assert [v.name for v in variants] == ["Nebraska Chamber of Commerce & Industry"]
    assert variants[0].record_count == 4129
