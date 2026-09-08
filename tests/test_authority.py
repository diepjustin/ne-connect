import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "build"))

from authority import authoritative_groups, short_circuit  # noqa: E402
from resolutions import UnionFind  # noqa: E402
from sources import Party  # noqa: E402


def principal(name, source_id):
    return Party(
        name=name, source="lobbying", role="principal",
        entity_type="organization", source_id=source_id,
    )


def vendor(name):
    return Party(name=name, source="contracts", role="vendor", entity_type="organization")


# The real case: the site truncates in its own markup, so one principal reaches
# us as two unmatchable strings that share an id.
TRUNCATED = "ASSOCIATED BEVERAGE DISTRIBUTORS OF"
FULL = "ASSOCIATED BEVERAGE DISTRIBUTORS OF NEBRASKA"

# The harder real case: principal 2590 is "Time Warner Cable" in the roster and
# "Charter Communications Operating, L..." in the positions table. The company
# was renamed; the id outlived the name.
OLD_NAME = "TIME WARNER CABLE"
NEW_NAME = "CHARTER COMMUNICATIONS OPERATING"


def test_ids_group_names_that_no_matcher_could_link():
    parties = {
        OLD_NAME: [principal("Time Warner Cable", "2590")],
        NEW_NAME: [principal("Charter Communications Operating, L...", "2590")],
    }
    groups = authoritative_groups(parties)
    assert groups == {("lobbying", "2590"): {OLD_NAME, NEW_NAME}}


def test_short_circuit_unions_a_renamed_entity():
    """No score is computed and none is needed -- the id settles it."""
    parties = {
        OLD_NAME: [principal("Time Warner Cable", "2590")],
        NEW_NAME: [principal("Charter Communications Operating, L...", "2590")],
    }
    clusters = UnionFind()
    links = short_circuit(clusters, parties)

    assert len(links) == 1
    assert links[0]["match_kind"] == "authoritative_id"
    assert links[0]["decision"] == "hard_id"
    assert "not by name similarity" in links[0]["reason"]
    assert clusters.find(OLD_NAME) == clusters.find(NEW_NAME)


def test_truncated_and_full_names_land_in_one_cluster():
    parties = {
        TRUNCATED: [principal("Associated Beverage Distributors of...", "2285")],
        FULL: [principal("Associated Beverage Distributors of Nebraska", "2285")],
    }
    clusters = UnionFind()
    short_circuit(clusters, parties)
    assert clusters.find(TRUNCATED) == clusters.find(FULL)


def test_one_later_match_attaches_the_whole_id_group():
    """The reason the hard-id pass runs FIRST.

    A vendor matched against only the full spelling still picks up the
    truncated alias, because they were already one cluster. Without this, the
    truncated row would need its own review even though it is the same entity.
    """
    parties = {
        TRUNCATED: [principal("Associated Beverage Distributors of...", "2285")],
        FULL: [principal("Associated Beverage Distributors of Nebraska", "2285")],
    }
    clusters = UnionFind()
    short_circuit(clusters, parties)

    # A later name-based match touches only the full spelling.
    clusters.union(FULL, "ASSOCIATED BEVERAGE DISTRIBUTORS OF NEBRASKA LLC")

    root = clusters.find("ASSOCIATED BEVERAGE DISTRIBUTORS OF NEBRASKA LLC")
    assert clusters.find(TRUNCATED) == root  # inherited, never re-reviewed


def test_sources_without_ids_are_untouched():
    """Contracts and campaign finance publish no entity id.

    They must fall through to matching, not be silently grouped by an empty id.
    """
    parties = {
        "ACME": [vendor("Acme Inc")],
        "ACME SUPPLY": [vendor("Acme Supply Co")],
    }
    assert authoritative_groups(parties) == {}
    clusters = UnionFind()
    assert short_circuit(clusters, parties) == []


def test_an_id_seen_under_one_name_needs_no_link():
    parties = {FULL: [principal("Associated Beverage Distributors of Nebraska", "2285")]}
    assert authoritative_groups(parties) == {}


def test_same_id_in_different_sources_is_not_the_same_entity():
    """Ids are authoritative WITHIN a source only.

    Lobbying principal 7 and some other source's id 7 are unrelated integers.
    Treating them as one entity would invent a link out of a coincidence.
    """
    parties = {
        "ALPHA": [principal("Alpha", "7")],
        "BETA": [Party(name="Beta", source="other", role="x", source_id="7")],
    }
    assert authoritative_groups(parties) == {}
