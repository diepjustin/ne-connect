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
# ne-fec writes its processed CSVs straight to data/, not data/processed/ --
# unlike ne-campaign-finance, there's only one pipeline stage here so there
# was nothing to separate raw from processed by directory.
FEC_DATA = REPO_ROOT / "ne-fec" / "data"
# nebraska-budget-data and nebraska-general-fund-receipts are NOT this
# project's own repos -- they belong to a third party (the professor whose
# course this project grew out of), cloned read-only the same way as every
# other sibling, but never pushed to. See docs/SCHEMA.md's "Self-published"
# sections for why these two sources don't follow the cross-fetch pattern
# the other four do: there is no live site on the other end to fetch from.
BUDGET_DATA = REPO_ROOT / "nebraska-budget-data"
BUDGET_FILE = "nebraska_budgets_all.csv"
GFR_DATA = REPO_ROOT / "nebraska-general-fund-receipts"
GFR_FILE = "data/nebraska_general_fund_receipts.csv"

CONTRACT_FILES = ("nu_contracts.csv", "nu_purchase_orders.csv", "state_agencies.csv")

# Stopgap front door for a budget entity with no report_link on its most
# recent row -- the Auditor's own bulk-query tool, same role as
# NADC_CONTRIBUTIONS_SEARCH_URL below.
NE_AUDITOR_BUDGET_URL = "https://www.nebraska.gov/auditor/reports/index.cgi?budget=1"

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
    # The single fiscal year total_amount is "as of" -- every other source's
    # total_amount is a SUM over record_count rows (every contract, every
    # contribution); a budget subdivision's is ONE recurring period's figure
    # (the most recent fiscal year's property tax request), never summed
    # across years, since unlike a one-time contract a tax request recurs
    # annually and summing it would overstate the total by an order of
    # magnitude. Empty for every other source.
    fiscal_year: str = ""


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


def load_campaign_filers(data_dir: Path = None, *, filename: str = "contributions.csv",
                          era: str = "modern"):
    """Campaign-finance filers (candidates/committees), keyed by (raw filer
    name, era) -- same era-keying reason as load_contributors(): a filer
    active in both eras must not have one era's Party clobber the other.

    entity_type="organization" always -- a filer is a registered committee,
    even when it is literally named after the candidate it supports.

    total_amount/record_count here is money RECEIVED (itemized contributions
    only, include_in_total rows -- matching what ne-campaign-finance's own
    site shows for a filer). Itemized SPENDING is a separate concept ne-connect
    fetches lazily from that project's d/expenditures.json, the same lazy
    pattern already used for contributions and lobbying positions -- see
    docs/SCHEMA.md's "Cross-fetch" sections. Never summed together: raising
    and spending are not the same figure.
    """
    data_dir = data_dir or CAMPAIGN_FINANCE_DATA
    path = data_dir / filename
    filers = {}
    if not path.exists():
        return filers

    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            filer_name = (row.get("filer_name") or "").strip()
            if not filer_name:
                continue
            # "filer:" prefix: a filer dict is merged with a contributor dict
            # by the caller ({**load_contributors(), **load_campaign_filers()})
            # -- without this, a name that happens to be both a contributor
            # and a filer in the same era would silently clobber one Party.
            key = ("filer:" + filer_name, era)
            party = filers.get(key)
            if party is None:
                party = filers[key] = Party(
                    name=filer_name,
                    source="campaign_finance",
                    role="filer",
                    era=era,
                    entity_type="organization",
                    sample_url=NADC_CONTRIBUTIONS_SEARCH_URL,
                )
            if row.get("include_in_total") == "True":
                party.record_count += 1
                try:
                    party.total_amount += float(row["amount"]) if row.get("amount") else 0.0
                except ValueError:
                    pass
    return filers


def load_legacy_campaign_filers(data_dir: Path = None):
    """Pre-2022 campaign filers, same wrapper pattern as load_legacy_contributors()."""
    return load_campaign_filers(data_dir, filename="contributions_legacy.csv", era="pre2022")


def load_spend_only_filers(data_dir: Path = None):
    """Filers that spent money but never appear as a filer_name in
    contributions.csv/contributions_legacy.csv at all -- every one of their
    itemized receipts was below the reporting threshold. Real but rare; skip
    it and that filer's spending is unreachable because the filer itself was
    never a searchable entity. era="modern" always here since expenditures.csv
    doesn't record which era a spend-only filer belongs to any more precisely
    than that; record_count/total_amount stay 0 -- this Party exists only so
    the entity is searchable, not to claim a receipts total.
    """
    data_dir = data_dir or CAMPAIGN_FINANCE_DATA
    known = set()
    for filename in ("contributions.csv", "contributions_legacy.csv"):
        path = data_dir / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            known.update(
                (row.get("filer_name") or "").strip() for row in csv.DictReader(fh)
            )

    filers = {}
    for filename in ("expenditures.csv", "expenditures_legacy.csv"):
        path = data_dir / filename
        if not path.exists():
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                filer_name = (row.get("filer_name") or "").strip()
                if filer_name and filer_name not in known:
                    key = ("filer:" + filer_name, "modern")
                    if key not in filers:
                        filers[key] = Party(
                            name=filer_name,
                            source="campaign_finance",
                            role="filer",
                            era="modern",
                            entity_type="organization",
                            sample_url=NADC_CONTRIBUTIONS_SEARCH_URL,
                        )
    return filers


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


def load_fec_committees(data_dir: Path = None):
    """FEC committees active in Nebraska, keyed by cmte_id.

    Organizations, not people -- a PAC or party committee, never a candidate.
    `source_url` already points at fec.gov's own committee page, so this
    carries no dependency on ne-fec (a local-only repo, no GitHub remote)
    ever being published.
    """
    data_dir = Path(data_dir or FEC_DATA)
    path = data_dir / "fec_committees_ne.csv"
    committees = {}
    if not path.exists():
        return committees

    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            cmte_id = (row.get("cmte_id") or "").strip()
            name = (row.get("cmte_name") or "").strip()
            if not cmte_id or not name:
                continue
            party = committees.get(cmte_id)
            if party is None:
                party = committees[cmte_id] = Party(
                    name=name,
                    source="fec",
                    role="committee",
                    entity_type="organization",
                    source_id=cmte_id,
                    sample_url=(row.get("source_url") or "").strip(),
                )
                city = (row.get("city") or "").strip().upper()
                if city:
                    party.cities.add(city)
            party.record_count += 1
    return committees


def load_fec_candidates(data_dir: Path = None):
    """FEC candidates who have run for a Nebraska office, keyed by cand_id.

    entity_type="individual" always -- a candidate is a real person, and
    PLAN.md Phase 3's "committees and candidates as organizations" line was
    wrong on this point (a name like "GRACE, DENNIS B." is exactly the kind
    of person match.py's involves_person guard exists to protect: it must
    never auto-merge with a vendor or contributor on name similarity alone).
    """
    data_dir = Path(data_dir or FEC_DATA)
    path = data_dir / "fec_candidates_ne.csv"
    candidates = {}
    if not path.exists():
        return candidates

    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            cand_id = (row.get("cand_id") or "").strip()
            name = (row.get("cand_name") or "").strip()
            if not cand_id or not name:
                continue
            party = candidates.get(cand_id)
            if party is None:
                party = candidates[cand_id] = Party(
                    name=name,
                    source="fec",
                    role="candidate",
                    entity_type="individual",
                    source_id=cand_id,
                    sample_url=(row.get("source_url") or "").strip(),
                )
                city = (row.get("city") or "").strip().upper()
                if city:
                    party.cities.add(city)
            party.record_count += 1
    return candidates


def load_fec_contributors(data_dir: Path = None):
    """FEC itemized contributors, keyed by raw name.

    Empty today: `fec_contributions_ne.csv` is header-only because
    `indiv24.zip` (4.24 GB) was deliberately not pulled yet (PLAN.md Phase 3)
    -- this reads whatever is there so it activates automatically once that
    decision changes, without anyone having to remember to wire it in later.
    `entity_tp == "IND"` is a real person and never auto-merges (match.py's
    involves_person guard); anything else is an organization (a PAC, a
    corporation making an independent expenditure, etc).
    """
    data_dir = Path(data_dir or FEC_DATA)
    path = data_dir / "fec_contributions_ne.csv"
    contributors = {}
    if not path.exists():
        return contributors

    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            party = contributors.get(name)
            if party is None:
                party = contributors[name] = Party(
                    name=name,
                    source="fec",
                    role="contributor",
                    entity_type="individual" if row.get("entity_tp") == "IND" else "organization",
                    sample_url=(row.get("source_url") or "").strip(),
                )
            party.record_count += 1
            try:
                party.total_amount += (
                    float(row["transaction_amt"]) if row.get("transaction_amt") else 0.0
                )
            except ValueError:
                pass
            city = (row.get("city") or "").strip().upper()
            if city:
                party.cities.add(city)
    return contributors


# The Auditor's own classification relabeled "Municipalities" to "Cities and
# Villages" at some point around FY2010-2011/2011-2012 -- confirmed
# empirically: every (county, name) pair carrying both labels has
# non-overlapping fiscal-year ranges (e.g. Abie, Butler County is
# "Municipalities" through FY2010-2011 and "Cities and Villages" from
# FY2011-2012 on, never both in the same year). Without this, 530 of
# Nebraska's cities/villages would each split into two Party objects with a
# truncated fiscal-year history apiece. The raw subdivision_type value from
# the CSV is never altered -- this mapping only affects the internal grouping
# key that decides entity identity.
_BUDGET_TYPE_RELABEL = {"Municipalities": "Cities and Villages"}


def _budget_group_key(row):
    county = (row.get("county_name") or "").strip()
    raw_type = (row.get("subdivision_type") or "").strip()
    subtype = _BUDGET_TYPE_RELABEL.get(raw_type, raw_type)
    name = (row.get("subdivision_name") or "").strip()
    return (county, subtype, name)


def _load_budget_groups(data_dir: Path = None):
    """(county_name, normalized_subdivision_type, subdivision_name) -> its
    rows, one per fiscal year on file. This is the CSV's real grain -- never
    group by bare subdivision_name, since two different real bodies can share
    a name (see _budget_name_collisions())."""
    data_dir = data_dir or BUDGET_DATA
    path = data_dir / BUDGET_FILE
    groups = defaultdict(list)
    if not path.exists():
        return groups
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if not (row.get("subdivision_name") or "").strip():
                continue
            groups[_budget_group_key(row)].append(row)
    return groups


def _budget_name_collisions(groups):
    """subdivision_name -> every distinct county_name it appears under, across
    every subdivision_type. Two genuinely different bodies sharing a name
    across counties is real, if rare: "Emerson Hubbard Public Schools" exists
    in both Dixon and Thurston County; "Wakefield CRA" in both Dixon and Wayne
    County (confirmed against the live 63,934-row file -- only these two).
    Both cases must never normalize to the same key and have their totals
    summed together.
    """
    by_name = defaultdict(set)
    for county, _subtype, name in groups:
        by_name[name].add(county)
    return {name: counties for name, counties in by_name.items() if len(counties) > 1}


def _budget_display_name(subdivision_name: str, county_name: str, collisions: dict) -> str:
    """subdivision_name unchanged, unless it appears under more than one
    county in this dataset -- then "<name> (<county_name>)" to keep it a
    distinct match target from its same-named counterpart elsewhere in the
    state. county_name already carries the word "County" (e.g. "Dixon
    County"), so this never doubles it up.
    """
    if subdivision_name in collisions:
        return f"{subdivision_name} ({county_name})"
    return subdivision_name


def load_budget_subdivisions(data_dir: Path = None):
    """Local-government subdivisions (counties, cities, school districts, fire
    districts, SIDs, NRDs, etc. -- every subdivision_type the state's budget
    filings cover), keyed by (county_name, subdivision_type, subdivision_name)
    -- see _load_budget_groups()/_budget_name_collisions() for why bare
    subdivision_name is unsafe.

    entity_type="organization" always -- every row here is a government body.
    This makes it automatically eligible for build_entities.py's org-only
    auto-accept band with no further changes needed there: nothing in
    resolve/ special-cases specific entity_type strings beyond the
    individual/organization binary that match.py's involves_person guard
    checks.

    total_amount is ONLY the most recent fiscal year's total_property_tax --
    never summed across years. Unlike a one-time contract award, a property
    tax request recurs annually; summing up to 27 years of them would
    overstate the total by an order of magnitude. record_count is years of
    budget history on file, not itemized transactions -- the full per-year
    history is load_budget_rows(), consumed separately by
    build/export_budget.py for the dossier's itemized table.
    """
    data_dir = data_dir or BUDGET_DATA
    groups = _load_budget_groups(data_dir)
    collisions = _budget_name_collisions(groups)

    subdivisions = {}
    for key, rows in groups.items():
        county, _subtype, name = key
        latest = max(rows, key=lambda r: r["fiscal_year"])
        subdivisions[key] = Party(
            name=_budget_display_name(name, county, collisions),
            source="budgets",
            role="subdivision",
            entity_type="organization",
            record_count=len(rows),
            total_amount=_money(latest.get("total_property_tax")),
            fiscal_year=latest.get("fiscal_year", ""),
            sample_url=(latest.get("report_link") or "").strip() or NE_AUDITOR_BUDGET_URL,
        )
    return subdivisions


def load_budget_rows(data_dir: Path = None):
    """Full per-fiscal-year history, keyed by the SAME display name
    load_budget_subdivisions() computes -- both derive it from the identical
    _load_budget_groups()/_budget_name_collisions() pair so the two artifacts
    can never drift apart on how a colliding name gets disambiguated.
    Consumed by build/export_budget.py's d/budget_rows.json, not by
    build_entities.py.

    Row: [fiscal_year, total_property_tax, valuation, outstanding_debt_total,
    total_resources_available, total_disbursements, unused_budget_authority,
    report_link], sorted newest fiscal_year first. unused_budget_authority is
    kept as the raw string (often literally "N/A" for school districts and
    some other subdivision types, per the source CSV) rather than coerced to
    0 -- "not applicable" and "zero" are different claims, and CLAUDE.md rule
    1 says the state's own words are shown unchanged or not at all.
    """
    data_dir = data_dir or BUDGET_DATA
    groups = _load_budget_groups(data_dir)
    collisions = _budget_name_collisions(groups)

    rows_by_name = {}
    for (county, _subtype, name), rows in groups.items():
        display_name = _budget_display_name(name, county, collisions)
        rows_by_name[display_name] = [
            [
                r.get("fiscal_year", ""),
                _money(r.get("total_property_tax")),
                _money(r.get("valuation")),
                _money(r.get("outstanding_debt_total")),
                _money(r.get("total_resources_available")),
                _money(r.get("total_disbursements")),
                (r.get("unused_budget_authority") or "").strip(),
                (r.get("report_link") or "").strip(),
            ]
            for r in sorted(rows, key=lambda r: r["fiscal_year"], reverse=True)
        ]
    return rows_by_name


def load_general_fund_receipts(data_dir: Path = None):
    """Statewide monthly General Fund receipts, actual vs. projected -- every
    (release, fiscal-month) row in the source CSV, newest release then newest
    data month first. Not Party-shaped and never touches build_entities.py or
    the resolution pipeline -- this is one single statewide series, not tied
    to any entity. Deliberately a thin, undecimated pass-through (this
    project's ingest adapters reshape, they don't decide what to keep); the
    source repo's own README explains why a given calendar month reappears in
    every release from when it's first reported through the end of that
    fiscal year -- it's what lets a reader track revisions to a month's
    figures over time. Collapsing to "the latest release's figure per month"
    for the page's compact always-visible table is a presentation decision,
    made in build/export_budget.py, not here.

    Row: [release_year, release_month, fiscal_year, data_year, data_month,
    data_month_name, actual_net_receipts, projected_net_receipts,
    cumulative_actual_net_receipts, cumulative_projected_net_receipts].
    units_scale_factor is not carried through -- the source repo's own
    parser already normalizes every dollar figure to full dollars regardless
    of how the source PDF printed it, per its README's "Methodology" section.
    """
    data_dir = data_dir or GFR_DATA
    path = data_dir / GFR_FILE
    if not path.exists():
        return []

    rows = []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            data_year = (row.get("data_year") or "").strip()
            data_month = (row.get("data_month") or "").strip()
            release_year = (row.get("release_year") or "").strip()
            release_month = (row.get("release_month") or "").strip()
            if not (data_year and data_month and release_year and release_month):
                continue
            rows.append((
                int(release_year), int(release_month), int(data_year), int(data_month),
                [
                    release_year, release_month,
                    row.get("fiscal_year", ""), int(data_year), int(data_month),
                    row.get("data_month_name", ""),
                    _money(row.get("actual_net_receipts")),
                    _money(row.get("projected_net_receipts")),
                    _money(row.get("cumulative_actual_net_receipts")),
                    _money(row.get("cumulative_projected_net_receipts")),
                ],
            ))
    rows.sort(key=lambda t: t[:4], reverse=True)
    return [r for *_sort_key, r in rows]
