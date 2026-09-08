"""Form C spending reaching the hub. No network, no real data."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ingest"))

from sources import load_lobbying_expenses, load_lobbying_principals  # noqa: E402

POSITIONS = """legislature,bill,lobbyist,lobbyist_id,principal,principal_id,position,registration_id,name_truncated
109,LB1,"Doe, Jane",11,Example Association,2446,Support,900,False
109,LB2,"Doe, Jane",11,Example Association,2446,Oppose,901,False
109,LB3,"Roe, Rick",12,Other Group,2447,Neutral,902,False
"""

DETAILS = """id,kind,name,address,city,state,zip,phone
2446,principal,Example Association,1 Main St,Lincoln,NE,68508,
2447,principal,Other Group,2 Elm Ave,Omaha,NE,68102,
"""

# Line 11 is the principal's total. Line 7 is a component of it, and line 1 is
# receipts -- neither may be added to the total or it double-counts.
EXPENSES = """form,entity_id,year,category,amount
C,2446,2025,"7.  Lobbyist Compensation paid by Principal",40000.00
C,2446,2025,"11. Total (Sum of 2, 3d, 4, 5, 6, 7, 8, 9d, and 10d)",50000.00
C,2446,2024,"11. Total (Sum of 2, 3d, 4, 5, 6, 7, 8, 9d, and 10d)",25000.00
C,2447,2025,"1. Total Receipts",99999.00
"""


def _dir(tmp_path, expenses=True):
    (tmp_path / "bill_positions.csv").write_text(POSITIONS)
    (tmp_path / "principal_details.csv").write_text(DETAILS)
    if expenses:
        (tmp_path / "expenses_principal.csv").write_text(EXPENSES)
    return tmp_path


def test_only_the_total_line_counts(tmp_path):
    """Line 7 is inside line 11; summing both would count it twice."""
    totals = load_lobbying_expenses(_dir(tmp_path))
    assert totals["2446"] == 75000.00  # 2025 + 2024 totals, not the line-7 40k


def test_receipts_are_not_spending(tmp_path):
    # Principal 2447 reported receipts only, which is not money it spent.
    assert "2447" not in load_lobbying_expenses(_dir(tmp_path))


def test_spending_reaches_the_principal(tmp_path):
    principals = load_lobbying_principals(_dir(tmp_path))
    assert principals["2446"].total_amount == 75000.00
    assert principals["2446"].record_count == 2  # two positions, one spend figure


def test_spending_is_not_multiplied_by_position_count(tmp_path):
    """The figure is per principal; accumulating per row would inflate it."""
    principals = load_lobbying_principals(_dir(tmp_path))
    assert principals["2446"].record_count == 2
    assert principals["2446"].total_amount == 75000.00


def test_missing_sweep_degrades_to_no_dollars(tmp_path):
    """The normal early state: positions collected, expenses not yet."""
    assert load_lobbying_expenses(_dir(tmp_path, expenses=False)) == {}
    principals = load_lobbying_principals(_dir(tmp_path, expenses=False))
    assert principals["2446"].total_amount == 0.0
    assert principals["2446"].record_count == 2
