"""_pairings() decides which two sources' keyed dicts get scored together.

Focused on the one behavior this module doesn't get elsewhere: fec_contributors
(individual itemized FEC donors) must pair against campaign_finance only, never
contracts/lobbying/disclosures -- those would only ever produce person-vs-
organization review-queue proposals with no auto-merge upside (match.py's
involves_person guard), and fec_contributors can run into the tens of thousands
of keys once indiv24.zip is pulled. fec_orgs (committees/candidates) keeps every
pairing the single merged "fec" dict used to have.
"""

from build_entities import _pairings

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
