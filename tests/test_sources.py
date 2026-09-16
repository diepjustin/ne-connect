"""Stopgap links set at ingest time. No network, no real data."""

from sources import (
    NADC_CONTRIBUTIONS_SEARCH_URL,
    NE_AUDITOR_BUDGET_URL,
    load_campaign_filers,
    load_budget_rows,
    load_budget_subdivisions,
    load_contributors,
    load_disclosure_filers,
    load_fec_candidates,
    load_fec_committees,
    load_fec_contributors,
    load_general_fund_receipts,
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


BUDGET_HEADER = (
    "county_name,subdivision_type,subdivision_name,fiscal_year,report_link,"
    "property_tax_bonds,property_tax_other,total_property_tax,valuation,"
    "outstanding_debt_principal,outstanding_debt_interest,outstanding_debt_total,"
    "total_resources_available,total_disbursements,unused_budget_authority\n"
)

# Two fiscal years for one real subdivision -- the older year should never
# win the "most recent" headline figure, and record_count should cover both.
BUDGET_ONE_SUBDIVISION = BUDGET_HEADER + (
    "Lancaster County,Cities and Villages,Lincoln,2025-2026,"
    "https://auditors.nebraska.gov/Budgets_Filed/2026/Lincoln_B2526.pdf,"
    "0,100000,100000,1000000,0,0,0,200000,180000,5000\n"
    "Lancaster County,Cities and Villages,Lincoln,2024-2025,"
    "https://auditors.nebraska.gov/Budgets_Filed/2025/Lincoln_B2425.pdf,"
    "0,90000,90000,900000,0,0,0,190000,170000,4000\n"
)

# The real shape found in the live 63,934-row file: two genuinely different
# bodies sharing a subdivision_name across counties.
BUDGET_COLLISION = BUDGET_HEADER + (
    "Dixon County,Community Redevelopment Author,Wakefield CRA,2015-2016,"
    "https://example.gov/dixon.pdf,0,0,0,0,0,0,0,1000,900,10\n"
    "Wayne County,Community Redevelopment Author,Wakefield CRA,2013-2014,"
    "https://example.gov/wayne.pdf,0,0,0,0,0,0,0,2000,1800,20\n"
)

# The real relabeling found in the live file: the same city under its old
# ("Municipalities") and new ("Cities and Villages") type label, never in
# the same fiscal year -- must merge into one Party, not split into two.
BUDGET_RELABEL = BUDGET_HEADER + (
    "Butler County,Cities and Villages,Abie,2025-2026,https://example.gov/new.pdf,"
    "0,10700,10700,4691182,0,0,0,158563,147500,475\n"
    "Butler County,Municipalities,Abie,2010-2011,https://example.gov/old.pdf,"
    "0,3500,3500,1390658,0,0,0,183030,172890,8543\n"
)

BUDGET_NO_REPORT_LINK = BUDGET_HEADER + (
    "Boyd County,Cities and Villages,Anoka,2020-2021,,"
    "0,500,500,50000,0,0,0,4000,3800,100\n"
)


def test_budget_subdivision_is_always_an_organization(tmp_path):
    (tmp_path / "nebraska_budgets_all.csv").write_text(BUDGET_ONE_SUBDIVISION)
    subs = load_budget_subdivisions(tmp_path)
    assert all(p.entity_type == "organization" for p in subs.values())


def test_budget_subdivision_amount_is_most_recent_fiscal_year_only(tmp_path):
    (tmp_path / "nebraska_budgets_all.csv").write_text(BUDGET_ONE_SUBDIVISION)
    subs = load_budget_subdivisions(tmp_path)
    party = subs[("Lancaster County", "Cities and Villages", "Lincoln")]
    assert party.total_amount == 100000.0
    assert party.fiscal_year == "2025-2026"


def test_budget_subdivision_record_count_is_years_on_file(tmp_path):
    (tmp_path / "nebraska_budgets_all.csv").write_text(BUDGET_ONE_SUBDIVISION)
    subs = load_budget_subdivisions(tmp_path)
    party = subs[("Lancaster County", "Cities and Villages", "Lincoln")]
    assert party.record_count == 2


def test_same_named_subdivisions_in_different_counties_do_not_collide(tmp_path):
    (tmp_path / "nebraska_budgets_all.csv").write_text(BUDGET_COLLISION)
    subs = load_budget_subdivisions(tmp_path)
    dixon = subs[("Dixon County", "Community Redevelopment Author", "Wakefield CRA")]
    wayne = subs[("Wayne County", "Community Redevelopment Author", "Wakefield CRA")]
    assert dixon.record_count == 1
    assert wayne.record_count == 1
    assert dixon.fiscal_year == "2015-2016"
    assert wayne.fiscal_year == "2013-2014"


def test_collision_disambiguates_display_name_with_county(tmp_path):
    (tmp_path / "nebraska_budgets_all.csv").write_text(BUDGET_COLLISION)
    subs = load_budget_subdivisions(tmp_path)
    dixon = subs[("Dixon County", "Community Redevelopment Author", "Wakefield CRA")]
    wayne = subs[("Wayne County", "Community Redevelopment Author", "Wakefield CRA")]
    assert dixon.name == "Wakefield CRA (Dixon County)"
    assert wayne.name == "Wakefield CRA (Wayne County)"
    assert dixon.name != wayne.name


def test_unique_subdivision_name_keeps_clean_display_name(tmp_path):
    (tmp_path / "nebraska_budgets_all.csv").write_text(BUDGET_ONE_SUBDIVISION)
    subs = load_budget_subdivisions(tmp_path)
    party = subs[("Lancaster County", "Cities and Villages", "Lincoln")]
    assert party.name == "Lincoln"


def test_municipalities_relabel_merges_into_one_subdivision(tmp_path):
    (tmp_path / "nebraska_budgets_all.csv").write_text(BUDGET_RELABEL)
    subs = load_budget_subdivisions(tmp_path)
    assert len(subs) == 1
    party = next(iter(subs.values()))
    assert party.record_count == 2
    assert party.fiscal_year == "2025-2026"
    assert party.total_amount == 10700.0


def test_budget_sample_url_falls_back_to_auditor_url_when_report_link_missing(tmp_path):
    (tmp_path / "nebraska_budgets_all.csv").write_text(BUDGET_NO_REPORT_LINK)
    subs = load_budget_subdivisions(tmp_path)
    party = subs[("Boyd County", "Cities and Villages", "Anoka")]
    assert party.sample_url == NE_AUDITOR_BUDGET_URL


def test_load_budget_rows_keyed_by_same_display_name_as_party(tmp_path):
    (tmp_path / "nebraska_budgets_all.csv").write_text(BUDGET_COLLISION)
    subs = load_budget_subdivisions(tmp_path)
    rows = load_budget_rows(tmp_path)
    for party in subs.values():
        assert party.name in rows


def test_load_budget_rows_sorted_newest_fiscal_year_first(tmp_path):
    (tmp_path / "nebraska_budgets_all.csv").write_text(BUDGET_ONE_SUBDIVISION)
    rows = load_budget_rows(tmp_path)
    fiscal_years = [r[0] for r in rows["Lincoln"]]
    assert fiscal_years == ["2025-2026", "2024-2025"]


def test_load_budget_rows_keeps_unused_authority_as_raw_string(tmp_path):
    header = BUDGET_HEADER
    row = (
        "Adams County,School Districts,Some Schools,2025-2026,https://example.gov/x.pdf,"
        "0,100,100,1000,0,0,0,200,180,N/A\n"
    )
    (tmp_path / "nebraska_budgets_all.csv").write_text(header + row)
    rows = load_budget_rows(tmp_path)
    assert rows["Some Schools"][0][6] == "N/A"


GFR_HEADER = (
    "release_year,release_month,fiscal_year,data_year,data_month,data_month_name,"
    "actual_net_receipts,projected_net_receipts,difference,percent_difference,"
    "cumulative_actual_net_receipts,cumulative_projected_net_receipts,"
    "cumulative_difference,cumulative_percent_difference,units_scale_factor,source_pdf\n"
)

# July reported by two releases -- the August release's figure is a revision
# of what the July release first reported. Only the newer one should win.
GFR_REVISED_MONTH = GFR_HEADER + (
    "2016,7,2016-2017,2016,7,July,234000000,253000000,-19000000,-7.5,"
    "234000000,253000000,-19000000,-7.5,1.0,2016-07.pdf\n"
    "2016,8,2016-2017,2016,7,July,234585213,253766000,-19180787,-7.6,"
    "234585213,253766000,-19180787,-7.6,1.0,2016-08.pdf\n"
    "2016,8,2016-2017,2016,8,August,410484016,408951000,1533016,0.37,"
    "645069230,662717000,-17647770,-2.66,1.0,2016-08.pdf\n"
)


def test_general_fund_receipts_loader_shape(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "nebraska_general_fund_receipts.csv").write_text(GFR_REVISED_MONTH)
    rows = load_general_fund_receipts(tmp_path)
    assert len(rows) == 3
    # newest (release, data month) first
    assert rows[0][:2] == ["2016", "8"]


def test_general_fund_receipts_is_undecimated(tmp_path):
    """Both releases reporting July must both be present -- collapsing to
    "latest release per month" is a presentation decision made in
    build/export_budget.py, not something the ingest adapter does."""
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "nebraska_general_fund_receipts.csv").write_text(GFR_REVISED_MONTH)
    rows = load_general_fund_receipts(tmp_path)
    july_rows = [r for r in rows if r[3] == 2016 and r[4] == 7]
    assert len(july_rows) == 2
