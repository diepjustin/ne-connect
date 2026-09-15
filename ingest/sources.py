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

# Each source is a separate GitHub repo (diepjustin/ne-contracts,
# ne-campaign-finance, ne-lobbying). This resolves correctly only when they
# are cloned as siblings of this repo -- e.g. all four directly under
# ~/Documents/GitHub/ -- since these paths read local, gitignored data that
# never leaves any of those repos' own working trees.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACTS_DATA = REPO_ROOT / "ne-contracts" / "data"
CAMPAIGN_FINANCE_DATA = REPO_ROOT / "ne-campaign-finance" / "data" / "processed"
LOBBYING_DATA = REPO_ROOT / "ne-lobbying" / "data"
# C-1/C-2 financial disclosures live in the same processed/ dir as campaign
# finance -- same repo (ne-campaign-finance), different pipeline.
DISCLOSURES_DATA = REPO_ROOT / "ne-campaign-finance" / "data" / "processed"

CONTRACT_FILES = ("nu_contracts.csv", "nu_purchase_orders.csv", "state_agencies.csv")

# Stopgap until Phase 1 ships a hosted, per-name campaign-finance search page:
# link to NADC's own contributions search instead of a dead end. Not
# per-name -- FirstTuesday's search is a WebForms POST, not a GET query
# string -- so the label says "search" rather than promising a direct hit.
NADC_CONTRIBUTIONS_SEARCH_URL = (
    "https://nadc-e.nebraska.gov/PublicSite/SearchPages/Search.aspx"
    "?SearchTypeCodeHook=F0FEA582-08C3-42BA-B008-0F5067C5791B"
)

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
    # "modern" (2022+) or "pre2022" (Phase 1.2's legacy tables). Same source,
    # same role, same hub bit either way -- era is a property of the record,
    # not a different source. Only campaign_finance has more than one era
    # today; every other source defaults to "modern" and means it literally.
    era: str = "modern"


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


def load_contributors(data_dir: Path = None, *, filename: str = "contributions.csv",
                       era: str = "modern"):
    """Campaign contributors, keyed by (raw source name, era).

    Individuals and organizations both, distinguished by entity_type -- the
    caller decides how much corroboration each demands.

    Keyed by (name, era) rather than bare name so the same donor name in both
    eras produces two distinct Party records rather than one clobbering the
    other -- Phase 1.4's canonical_entities.csv wants one row per
    (alias, source, era), and that split has to survive from here through
    build_entities.py's _keyed(), which only ever sees Party.name/.era, not
    this dict's own keys.
    """
    data_dir = data_dir or CAMPAIGN_FINANCE_DATA
    path = data_dir / filename
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
            key = (name, era)
            party = contributors.get(key)
            if party is None:
                party = contributors[key] = Party(
                    name=name,
                    source="campaign_finance",
                    role="contributor",
                    era=era,
                    entity_type=(
                        "individual" if row.get("source_type") == "Individual" else "organization"
                    ),
                    sample_url=NADC_CONTRIBUTIONS_SEARCH_URL,
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


def load_legacy_contributors(data_dir: Path = None):
    """Pre-2022 campaign contributors from Phase 1.2's contributions_legacy.csv.

    Same shape as load_contributors(), just pointed at the legacy table with
    era="pre2022". A thin wrapper because Phase 1.4's spec names it
    explicitly as its own function, distinct from passing filename/era by
    hand at every call site.
    """
    return load_contributors(data_dir, filename="contributions_legacy.csv", era="pre2022")


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

    # The Legislature's own pages list some registrations twice (verified
    # against a cached page -- see ne-lobbying's check_data.py, which defines
    # a position's natural key the same way). Counting every raw row would
    # inflate a principal's displayed position count by however many of its
    # own rows are byte-identical repeats -- 15% of all rows sitewide.
    seen_positions = set()

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

            position_key = (
                row.get("legislature"), row.get("bill"), row.get("registration_id"),
                row.get("position"),
            )
            if position_key not in seen_positions:
                seen_positions.add(position_key)
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


def load_disclosure_filers(data_dir: Path = None):
    """C-1/C-2 financial-interest filers, keyed by disclosure_id.

    entity_type="individual" always -- these are public officials filing a
    disclosure, not organizations (PLAN.md Phase 1.5). Individuals never
    auto-merge (resolve/match.py's involves_person guard), so listing them
    here is safe: they become searchable and land in the review queue like
    any cross-source person match, but nothing merges them automatically.

    Deliberately does NOT ingest financial_interests.csv's
    counterparty_name_raw as organizations yet. A real check of the data this
    scraper produced (2026-09-15) found several item types -- real_property,
    other_financial_interest, gift -- whose text is extracted by a line-
    fallback parser that, on a mostly-blank filing, picks up the form's own
    instructional boilerplate ("personal residence need not be reported.")
    as if it were a filer's actual answer. Shipping that into
    canonical_entities.csv would put fake "organizations" in a public search
    index. Only income_source/business_association/creditor use a more
    reliable numbered-entry parser, but splitting by item_type here felt
    like exactly the kind of judgment call this project defers to a human
    rather than making silently -- see ne-campaign-finance's
    build_financial_interests.py for the item-type breakdown.
    """
    data_dir = Path(data_dir or DISCLOSURES_DATA)
    filings_path = data_dir / "c1_filings.csv"
    items_path = data_dir / "financial_interests.csv"
    filers = {}
    if not filings_path.exists():
        return filers

    with filings_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            disclosure_id = (row.get("disclosure_id") or "").strip()
            name = (row.get("filer_name_raw") or "").strip()
            if not disclosure_id or not name:
                continue
            filers[disclosure_id] = Party(
                name=name,
                source="disclosures",
                role="filer",
                entity_type="individual",
                source_id=disclosure_id,
                sample_url=(row.get("document_url") or "").strip(),
            )

    if items_path.exists():
        with items_path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                party = filers.get((row.get("disclosure_id") or "").strip())
                if party:
                    party.record_count += 1
    return filers
