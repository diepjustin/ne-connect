"""Stopgap links set at ingest time. No network, no real data."""

from sources import (
    NADC_CONTRIBUTIONS_SEARCH_URL,
    load_campaign_filers,
    load_contributors,
    load_disclosure_filers,
    load_fec_candidates,
    load_fec_committees,
    load_fec_contributors,
    load_legacy_campaign_filers,
    load_legacy_contributors,
    load_spend_only_filers,
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


FEC_COMMITTEES = (
    "cmte_id,cmte_name,treasurer_name,city,state,zip,cmte_designation,cmte_type,"
    "cmte_party_affiliation,org_type,connected_org_name,cand_id,cycle,source_url,"
    "source_snapshot\n"
    "C00003988,NEBRASKA DEMOCRATIC PARTY,\"KESSLER, TED\",LINCOLN,NE,68510,U,Y,DEM,"
    ",DNC NE STATE PARTY VICTORY FUND,,2024,https://www.fec.gov/data/committee/"
    "C00003988/,2026-09-15T06:01:24Z\n"
)

FEC_CANDIDATES = (
    "cand_id,cand_name,cand_party_affiliation,cand_election_yr,cand_office_st,"
    "cand_office,cand_office_district,cand_ici,cand_status,cand_pcc,city,state,"
    "zip,cycle,source_url,source_snapshot\n"
    "H0NE01146,\"GRACE, DENNIS B.\",LIB,2020,NE,H,01,C,N,C00752485,FREMONT,NE,"
    "68025,2024,https://www.fec.gov/data/candidate/H0NE01146/,2026-09-15T06:01:24Z\n"
)

FEC_CONTRIBUTIONS = (
    "sub_id,cmte_id,cmte_name,amndt_ind,rpt_tp,transaction_tp,entity_tp,name,"
    "city,state,zip,transaction_dt,transaction_amt,other_id,tran_id,file_num,"
    "image_num,cycle,source_url,source_snapshot\n"
    "1,C00003988,NEBRASKA DEMOCRATIC PARTY,N,Q1,15,IND,\"DOE, JANE\",OMAHA,NE,"
    "68102,20240115,250.00,,T1,1,IMG1,2024,https://docquery.fec.gov/cgi-bin/"
    "fecimg/?IMG1,2026-09-15T06:01:24Z\n"
)


def test_fec_committee_is_always_an_organization(tmp_path):
    (tmp_path / "fec_committees_ne.csv").write_text(FEC_COMMITTEES)
    committees = load_fec_committees(tmp_path)
    assert committees["C00003988"].entity_type == "organization"
    assert committees["C00003988"].source == "fec"
    assert committees["C00003988"].role == "committee"
    assert committees["C00003988"].sample_url == "https://www.fec.gov/data/committee/C00003988/"


def test_fec_candidate_is_always_an_individual(tmp_path):
    """PLAN.md's Phase 3 line said 'candidates as organizations' -- a real
    person's name must never be able to auto-merge with a vendor, so this
    is entity_type='individual' regardless of what the plan originally said."""
    (tmp_path / "fec_candidates_ne.csv").write_text(FEC_CANDIDATES)
    candidates = load_fec_candidates(tmp_path)
    assert candidates["H0NE01146"].entity_type == "individual"
    assert candidates["H0NE01146"].source == "fec"


def test_fec_contributors_empty_when_file_is_header_only(tmp_path):
    """indiv24.zip hasn't been pulled -- fec_contributions_ne.csv exists but
    has zero data rows. This must return {} cleanly, not error."""
    (tmp_path / "fec_contributions_ne.csv").write_text(FEC_CONTRIBUTIONS.splitlines()[0] + "\n")
    assert load_fec_contributors(tmp_path) == {}


def test_fec_individual_contributor_parsed_when_present(tmp_path):
    (tmp_path / "fec_contributions_ne.csv").write_text(FEC_CONTRIBUTIONS)
    contributors = load_fec_contributors(tmp_path)
    assert contributors["DOE, JANE"].entity_type == "individual"
    assert contributors["DOE, JANE"].total_amount == 250.0


FEC_ORG_CONTRIBUTION = (
    "sub_id,cmte_id,cmte_name,amndt_ind,rpt_tp,transaction_tp,entity_tp,name,"
    "city,state,zip,transaction_dt,transaction_amt,other_id,tran_id,file_num,"
    "image_num,cycle,source_url,source_snapshot\n"
    "2,C00003988,NEBRASKA DEMOCRATIC PARTY,N,Q1,24K,ORG,SOME PAC,OMAHA,NE,"
    "68102,20240115,500.00,,T2,1,IMG2,2024,https://docquery.fec.gov/cgi-bin/"
    "fecimg/?IMG2,2026-09-15T06:01:24Z\n"
)


def test_fec_non_individual_contributor_is_an_organization(tmp_path):
    """entity_tp values other than IND -- a PAC, a corporation making an
    independent expenditure -- are organizations, not people; only IND rows
    ever hit match.py's involves_person guard."""
    (tmp_path / "fec_contributions_ne.csv").write_text(FEC_ORG_CONTRIBUTION)
    contributors = load_fec_contributors(tmp_path)
    assert contributors["SOME PAC"].entity_type == "organization"


def test_campaign_filer_is_always_an_organization(tmp_path):
    (tmp_path / "contributions.csv").write_text(CONTRIBUTIONS)
    filers = load_campaign_filers(tmp_path)
    party = filers[("filer:Some Committee", "modern")]
    assert party.entity_type == "organization"
    assert party.source == "campaign_finance"
    assert party.role == "filer"
    assert party.total_amount == 100.0


def test_campaign_filer_key_never_collides_with_a_contributor_key(tmp_path):
    """load_campaign_filers()'s dict is merged with load_contributors()'s via
    {**a, **b} in build_entities.py -- without the "filer:" key prefix, a
    name that happens to be both a contributor and a filer in the same era
    would silently clobber one Party."""
    same_name = "Jane Doe,Individual,100.00,True,Jane Doe,Lincoln\n"
    (tmp_path / "contributions.csv").write_text(
        "source_name,source_type,amount,include_in_total,filer_name,city\n" + same_name
    )
    contributors = load_contributors(tmp_path)
    filers = load_campaign_filers(tmp_path)
    merged = {**contributors, **filers}
    assert len(merged) == 2


def test_legacy_campaign_filer_is_tagged_pre2022(tmp_path):
    (tmp_path / "contributions_legacy.csv").write_text(CONTRIBUTIONS)
    filers = load_legacy_campaign_filers(tmp_path)
    assert filers[("filer:Some Committee", "pre2022")].era == "pre2022"


def test_spend_only_filer_gets_an_entity_with_zero_receipts(tmp_path):
    """A filer that spent money but never appears as a filer_name in
    contributions.csv at all -- every itemized receipt was below the
    reporting threshold. Without this, the entity (and its spending) would
    be unreachable."""
    (tmp_path / "expenditures.csv").write_text(
        "filer_name,expenditure_date,amount,payee_name,include_in_total\n"
        "Ghost Committee,2025-01-01,500.00,Print Shop,True\n"
    )
    filers = load_spend_only_filers(tmp_path)
    party = filers[("filer:Ghost Committee", "modern")]
    assert party.entity_type == "organization"
    assert party.record_count == 0
    assert party.total_amount == 0.0


def test_spend_only_filer_skipped_when_already_a_known_filer(tmp_path):
    (tmp_path / "contributions.csv").write_text(CONTRIBUTIONS)
    (tmp_path / "expenditures.csv").write_text(
        "filer_name,expenditure_date,amount,payee_name,include_in_total\n"
        "Some Committee,2025-01-01,500.00,Print Shop,True\n"
    )
    filers = load_spend_only_filers(tmp_path)
    assert filers == {}
