"""Stopgap links set at ingest time. No network, no real data."""

from sources import (
    NADC_CONTRIBUTIONS_SEARCH_URL,
    load_contributors,
    load_disclosure_filers,
    load_legacy_contributors,
)

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


C1_FILINGS = """disclosure_id,year,filer_name_raw,filer_office,filed_method,filing_reason,filed_date,document_url,retrieved_at
abc-123,2023,JANE DOE,COUNTY COMMISSIONER,Manual,Annual report,2/16/2024,https://example.gov/abc-123,2026-09-15
"""

FINANCIAL_INTERESTS = """disclosure_id,item_type,counterparty_name_raw,detail,source_url,retrieved_at,ocr
abc-123,creditor,Some Bank,,https://example.gov/abc-123,2026-09-15,False
abc-123,income_source,Some Employer,,https://example.gov/abc-123,2026-09-15,False
"""


def test_disclosure_filer_is_always_an_individual(tmp_path):
    (tmp_path / "c1_filings.csv").write_text(C1_FILINGS)
    filers = load_disclosure_filers(tmp_path)
    assert filers["abc-123"].entity_type == "individual"
    assert filers["abc-123"].source == "disclosures"
    assert filers["abc-123"].role == "filer"


def test_disclosure_filer_record_count_is_item_count(tmp_path):
    (tmp_path / "c1_filings.csv").write_text(C1_FILINGS)
    (tmp_path / "financial_interests.csv").write_text(FINANCIAL_INTERESTS)
    filers = load_disclosure_filers(tmp_path)
    assert filers["abc-123"].record_count == 2


def test_disclosure_filer_links_to_the_real_document(tmp_path):
    (tmp_path / "c1_filings.csv").write_text(C1_FILINGS)
    filers = load_disclosure_filers(tmp_path)
    assert filers["abc-123"].sample_url == "https://example.gov/abc-123"
