"""build/export_budget.py -- no network, no real data."""

import json

import export_budget
import sources


BUDGET_HEADER = (
    "county_name,subdivision_type,subdivision_name,fiscal_year,report_link,"
    "property_tax_bonds,property_tax_other,total_property_tax,valuation,"
    "outstanding_debt_principal,outstanding_debt_interest,outstanding_debt_total,"
    "total_resources_available,total_disbursements,unused_budget_authority\n"
)
BUDGET_ROW = (
    "Lancaster County,Cities and Villages,Lincoln,2025-2026,"
    "https://auditors.nebraska.gov/Budgets_Filed/2026/Lincoln_B2526.pdf,"
    "0,100000,100000,1000000,0,0,0,200000,180000,5000\n"
)

GFR_HEADER = (
    "release_year,release_month,fiscal_year,data_year,data_month,data_month_name,"
    "actual_net_receipts,projected_net_receipts,difference,percent_difference,"
    "cumulative_actual_net_receipts,cumulative_projected_net_receipts,"
    "cumulative_difference,cumulative_percent_difference,units_scale_factor,source_pdf\n"
)
GFR_TWO_RELEASES_SAME_MONTH = GFR_HEADER + (
    "2016,7,2016-2017,2016,7,July,234000000,253000000,-19000000,-7.5,"
    "234000000,253000000,-19000000,-7.5,1.0,2016-07.pdf\n"
    "2016,8,2016-2017,2016,7,July,234585213,253766000,-19180787,-7.6,"
    "234585213,253766000,-19180787,-7.6,1.0,2016-08.pdf\n"
    "2016,8,2016-2017,2016,8,August,410484016,408951000,1533016,0.37,"
    "645069230,662717000,-17647770,-2.66,1.0,2016-08.pdf\n"
)


def test_budget_rows_json_shape_matches_docs(tmp_path, monkeypatch):
    (tmp_path / "nebraska_budgets_all.csv").write_text(BUDGET_HEADER + BUDGET_ROW)
    monkeypatch.setattr(sources, "BUDGET_DATA", tmp_path)

    out_path = tmp_path / "budget_rows.json"
    export_budget.write_budget_rows_json(out_path)
    payload = json.loads(out_path.read_text())

    assert "Lincoln" in payload
    row = payload["Lincoln"][0]
    assert row == [
        "2025-2026", 100000.0, 1000000.0, 0.0, 200000.0, 180000.0, "5000",
        "https://auditors.nebraska.gov/Budgets_Filed/2026/Lincoln_B2526.pdf",
    ]


def test_general_fund_receipts_json_is_undecimated(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "nebraska_general_fund_receipts.csv").write_text(GFR_TWO_RELEASES_SAME_MONTH)
    monkeypatch.setattr(sources, "GFR_DATA", tmp_path)

    out_path = tmp_path / "gfr.json"
    export_budget.write_general_fund_receipts_json(out_path)
    payload = json.loads(out_path.read_text())

    assert len(payload) == 3  # both July releases kept, not collapsed


def test_latest_gfr_by_month_keeps_only_the_newest_release_per_month(tmp_path, monkeypatch):
    """The collapsing step for the page's always-visible compact table --
    the OLDER July release's figures must not survive."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "nebraska_general_fund_receipts.csv").write_text(GFR_TWO_RELEASES_SAME_MONTH)
    monkeypatch.setattr(sources, "GFR_DATA", tmp_path)

    collapsed = export_budget.latest_gfr_by_month()

    july_rows = [r for r in collapsed if r[1] == 2016 and r[2] == "July"]
    assert len(july_rows) == 1
    assert july_rows[0][3] == 234585213.0  # the August release's (newer) July figure, not the original


def test_latest_gfr_by_month_covers_every_distinct_month(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "nebraska_general_fund_receipts.csv").write_text(GFR_TWO_RELEASES_SAME_MONTH)
    monkeypatch.setattr(sources, "GFR_DATA", tmp_path)

    collapsed = export_budget.latest_gfr_by_month()

    assert len(collapsed) == 2  # July and August, each once
