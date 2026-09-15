"""Stopgap links set at ingest time. No network, no real data."""

from sources import NADC_CONTRIBUTIONS_SEARCH_URL, load_contributors, load_legacy_contributors

CONTRIBUTIONS = """source_name,source_type,amount,include_in_total,filer_name,city
Jane Doe,Individual,100.00,True,Some Committee,Lincoln
"""


def test_contributor_links_to_the_nadc_search_page(tmp_path):
    (tmp_path / "contributions.csv").write_text(CONTRIBUTIONS)
    contributors = load_contributors(tmp_path)
    assert contributors[("Jane Doe", "modern")].sample_url == NADC_CONTRIBUTIONS_SEARCH_URL


def test_modern_contributor_defaults_to_modern_era(tmp_path):
    (tmp_path / "contributions.csv").write_text(CONTRIBUTIONS)
    contributors = load_contributors(tmp_path)
    assert contributors[("Jane Doe", "modern")].era == "modern"


def test_legacy_contributor_is_tagged_pre2022(tmp_path):
    (tmp_path / "contributions_legacy.csv").write_text(CONTRIBUTIONS)
    contributors = load_legacy_contributors(tmp_path)
    assert contributors[("Jane Doe", "pre2022")].era == "pre2022"


def test_same_name_both_eras_produces_two_distinct_parties(tmp_path):
    """The whole point of keying by (name, era): a donor who gave in both
    eras must not have one era's Party silently overwrite the other's."""
    (tmp_path / "contributions.csv").write_text(CONTRIBUTIONS)
    (tmp_path / "contributions_legacy.csv").write_text(CONTRIBUTIONS)
    modern = load_contributors(tmp_path)
    legacy = load_legacy_contributors(tmp_path)
    merged = {**modern, **legacy}
    assert len(merged) == 2
    assert merged[("Jane Doe", "modern")].total_amount == 100.0
    assert merged[("Jane Doe", "pre2022")].total_amount == 100.0
