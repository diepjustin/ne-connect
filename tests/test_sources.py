"""Stopgap links set at ingest time. No network, no real data."""

from sources import NADC_CONTRIBUTIONS_SEARCH_URL, load_contributors

CONTRIBUTIONS = """source_name,source_type,amount,include_in_total,filer_name,city
Jane Doe,Individual,100.00,True,Some Committee,Lincoln
"""


def test_contributor_links_to_the_nadc_search_page(tmp_path):
    (tmp_path / "contributions.csv").write_text(CONTRIBUTIONS)
    contributors = load_contributors(tmp_path)
    assert contributors["Jane Doe"].sample_url == NADC_CONTRIBUTIONS_SEARCH_URL
