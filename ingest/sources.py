"""Thin adapters: each source -> a common (name, role, count, amount) shape.

Deliberately thin. The scrapers keep their own repos, READMEs and caveats
(see README.md, "Architecture"); these adapters only reshape what those
projects already publish. Anything that needs explaining about a source belongs
in that source's own README, not here.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACTS_DATA = REPO_ROOT / "ne-contracts" / "data"
CAMPAIGN_FINANCE_DATA = REPO_ROOT / "ne-campaign-finance" / "data" / "processed"
LOBBYING_DATA = REPO_ROOT / "ne-lobbying" / "data"

CONTRACT_FILES = ("nu_contracts.csv", "nu_purchase_orders.csv", "state_agencies.csv")

# csv defaults to 128 KB; ne-contracts has contract descriptions well past it.
csv.field_size_limit(sys.maxsize)


@dataclass
class Party:
    """One named party in one source, with its totals and a sample record."""

    name: str
    source: str
    role: str
    record_count: int = 0
    total_amount: float = 0.0
    counterparties: set = field(default_factory=set)
    sample_url: str = ""
    cities: set = field(default_factory=set)
    entity_type: str = ""
    # A source-native identifier, where the source publishes one. Lobbying does;
    # contracts and campaign finance do not, which is precisely why those two
    # have to be matched by name. See resolve/authority.py.
    source_id: str = ""


def _money(raw: str) -> float:
    raw = (raw or "").strip().replace("$", "").replace(",", "")
    if not raw:
        return 0.0
    negative = raw.startswith("(") and raw.endswith(")")
    try:
        value = float(raw.strip("()"))
    except ValueError:
        return 0.0
    return -value if negative else value


def load_contract_vendors(data_dir: Path = None):
    """Vendors paid by the state, keyed by raw vendor string."""
    data_dir = data_dir or CONTRACTS_DATA
    vendors = {}
    for filename in CONTRACT_FILES:
        path = data_dir / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                name = (row.get("Vendor") or "").strip()
                if not name:
                    continue
                party = vendors.get(name)
                if party is None:
                    party = vendors[name] = Party(
                        name=name, source="contracts", role="vendor", entity_type="organization"
                    )
                party.record_count += 1
                party.total_amount += _money(row.get("Amount"))
                agency = (row.get("Entity Name") or "").strip()
                if agency:
                    party.counterparties.add(agency)
                if not party.sample_url:
                    party.sample_url = (row.get("Detail URL") or "").strip()
    return vendors


def load_contributors(data_dir: Path = None):
    """Campaign contributors, keyed by raw source name.

    Individuals and organizations both, distinguished by entity_type -- the
    caller decides how much corroboration each demands.
    """
    data_dir = data_dir or CAMPAIGN_FINANCE_DATA
    path = data_dir / "contributions.csv"
    contributors = {}
    if not path.exists():
        return contributors

    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("include_in_total") != "True":
                continue  # see ne-campaign-finance README: avoids double-counting
            name = (row.get("source_name") or "").strip()
            if not name:
                continue
            party = contributors.get(name)
            if party is None:
                party = contributors[name] = Party(
                    name=name,
                    source="campaign_finance",
                    role="contributor",
                    entity_type=(
                        "individual" if row.get("source_type") == "Individual" else "organization"
                    ),
                )
            party.record_count += 1
            try:
                party.total_amount += float(row["amount"]) if row.get("amount") else 0.0
            except ValueError:
                pass
            recipient = (row.get("filer_name") or "").strip()
            if recipient:
                party.counterparties.add(recipient)
            city = (row.get("city") or "").strip().upper()
            if city:
                party.cities.add(city)
    return contributors


def structured_contributor_names(data_dir: Path = None):
    """Raw source_name -> (last, first) for individuals, for person keys."""
    data_dir = data_dir or CAMPAIGN_FINANCE_DATA
    path = data_dir / "contributions.csv"
    names = defaultdict(set)
    if not path.exists():
        return names
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if row.get("source_type") != "Individual":
                continue
            name = (row.get("source_name") or "").strip()
            if name:
                names[name].add(
                    (row.get("source_last_name", ""), row.get("source_first_name", ""))
                )
    return names


def load_lobbying_expenses(data_dir: Path = None):
    """principal_id -> reported lobbying spending, from Form C.

    Form C line 11 is a principal's total: lobbyist compensation and
    reimbursement plus entertainment, lodging, travel, gifts and admissions. It
    is the fuller answer to "what did this organization spend on lobbying" than
    compensation alone.

    Form B is deliberately NOT read here. It reports what a LOBBYIST received
    for the same work, so adding the two would count the same money twice --
    the hub's lobbying entities are principals, and Form C is their side of it.

    Returns {} when the sweep has not run, which is the normal early state; the
    hub then shows positions without dollars rather than showing zeroes.
    """
    data_dir = Path(data_dir or LOBBYING_DATA)
    path = data_dir / "expenses_principal.csv"
    totals = {}
    if not path.exists():
        return totals

    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            # "11. Total (Sum of 2, 3d, 4, 5, 6, 7, 8, 9d, and 10d)"
            if not row.get("category", "").strip().startswith("11."):
                continue
            entity_id = (row.get("entity_id") or "").strip()
            if not entity_id:
                continue
            try:
                totals[entity_id] = totals.get(entity_id, 0.0) + float(row["amount"])
            except (KeyError, ValueError):
                continue
    return totals


def load_lobbying_principals(data_dir: Path = None):
    """Lobbying principals, keyed by the name we can best stand behind.

    Two files, and both are needed. `principal_details.csv` carries the full
    untruncated name from each principal's detail page; `bill_positions.csv`
    carries the activity, but with names the site truncated in its own markup.
    Rows are keyed by id and named from the detail file, so a truncated string
    never becomes an entity name.

    Every party carries `source_id`, which lets resolve/authority.py link the
    aliases without scoring them.
    """
    data_dir = Path(data_dir or LOBBYING_DATA)
    details_path = data_dir / "principal_details.csv"
    positions_path = data_dir / "bill_positions.csv"

    names = {}
    if details_path.exists():
        with details_path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("name"):
                    names[row["id"]] = row

    expenses = load_lobbying_expenses(data_dir)

    principals = {}
    if not positions_path.exists():
        return principals

    with positions_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            source_id = (row.get("principal_id") or "").strip()
            if not source_id:
                continue
            detail = names.get(source_id, {})
            # Prefer the detail-page name; fall back to the table's, truncated
            # or not, so an unresolved id still appears rather than vanishing.
            name = detail.get("name") or (row.get("principal") or "").strip()
            if not name:
                continue

            party = principals.get(source_id)
            if party is None:
                party = principals[source_id] = Party(
                    name=name,
                    source="lobbying",
                    role="principal",
                    entity_type="organization",
                    source_id=source_id,
                )
                city = (detail.get("city") or "").strip().upper()
                if city:
                    party.cities.add(city)
                party.sample_url = (
                    "https://nebraskalegislature.gov/lobbyist/"
                    f"view.php?link=view_principal&id={source_id}"
                )
                # Spending is per principal, not per position row, so it is set
                # once when the party is created rather than accumulated.
                party.total_amount = expenses.get(source_id, 0.0)
            party.record_count += 1
            lobbyist = (row.get("lobbyist") or "").strip()
            if lobbyist:
                party.counterparties.add(lobbyist)
    return principals


def load_lobbying_aliases(data_dir: Path = None):
    """Every distinct name string seen for each principal id.

    The truncated table name and the full detail-page name are different
    strings for one entity. Both are returned so authority.py can union them --
    that union is what makes a later match on either one attach the whole group.
    """
    data_dir = Path(data_dir or LOBBYING_DATA)
    aliases = defaultdict(set)

    positions_path = data_dir / "bill_positions.csv"
    if positions_path.exists():
        with positions_path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("principal_id") and row.get("principal"):
                    aliases[row["principal_id"]].add(row["principal"].strip())

    details_path = data_dir / "principal_details.csv"
    if details_path.exists():
        with details_path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                if row.get("id") and row.get("name"):
                    aliases[row["id"]].add(row["name"].strip())
    return aliases
