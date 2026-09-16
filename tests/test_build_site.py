import csv
import json

import build_site
from build_site import INDEX_COLUMNS, build_full_index, retrieval_dates


def _rows(*entities):
    """entities: list of (entity_id, canonical_name, alias, source, records, amount, source_id)."""
    return [
        {
            "entity_id": e[0],
            "canonical_name": e[1],
            "alias": e[2],
            "source": e[3],
            "records": e[4],
            "amount": e[5],
            "source_id": e[6],
        }
        for e in entities
    ]


def test_header_matches_row_length():
    rows = _rows(("1", "ACME CO", "ACME CO", "contracts", 3, 100.0, ""))
    index = build_full_index(rows)
    assert len(index[0]) == len(INDEX_COLUMNS)


def test_one_alias_entity_has_empty_alias_cell():
    rows = _rows(("1", "ACME CO", "ACME CO", "contracts", 3, 100.0, ""))
    index = build_full_index(rows)
    aliases_col = INDEX_COLUMNS.index("aliases")
    assert index[0][aliases_col] == []


def test_multi_alias_entity_lists_the_others_not_the_canonical_name():
    rows = _rows(
        ("1", "ACME CO", "ACME CO", "contracts", 3, 100.0, ""),
        ("1", "ACME CO", "ACME COMPANY", "contracts", 1, 10.0, ""),
    )
    index = build_full_index(rows)
    aliases_col = INDEX_COLUMNS.index("aliases")
    assert index[0][aliases_col] == ["ACME COMPANY"]


def test_lobbying_entity_carries_its_source_id():
    rows = _rows(("1", "ACME CO", "ACME CO", "lobbying", 4, 0.0, "9001"))
    index = build_full_index(rows)
    lobby_id_col = INDEX_COLUMNS.index("lobby_id")
    assert index[0][lobby_id_col] == "9001"


def test_non_lobbying_entity_has_empty_lobby_id():
    rows = _rows(("1", "ACME CO", "ACME CO", "contracts", 3, 100.0, ""))
    index = build_full_index(rows)
    lobby_id_col = INDEX_COLUMNS.index("lobby_id")
    assert index[0][lobby_id_col] == ""


def test_fec_entity_carries_a_record_count():
    rows = _rows(("1", "NEBRASKA DEMOCRATIC PARTY", "NEBRASKA DEMOCRATIC PARTY", "fec", 1, 0.0, "C00003988"))
    index = build_full_index(rows)
    fec_recs_col = INDEX_COLUMNS.index("fec_recs")
    assert index[0][fec_recs_col] == 1


def test_non_fec_entity_has_zero_fec_recs():
    rows = _rows(("1", "ACME CO", "ACME CO", "contracts", 3, 100.0, ""))
    index = build_full_index(rows)
    fec_recs_col = INDEX_COLUMNS.index("fec_recs")
    assert index[0][fec_recs_col] == 0


def _budget_row(entity_id, name, records, amount, fiscal_year):
    return {
        "entity_id": entity_id, "canonical_name": name, "alias": name,
        "source": "budgets", "records": records, "amount": amount,
        "source_id": "", "fiscal_year": fiscal_year,
    }


def test_budget_entity_gets_fiscal_year_in_the_lazy_index():
    """budget_amt/budget_recs/budget_fy mirror every other source's pair in
    INDEX_COLUMNS, but budget_amt is the snapshot most-recent-year figure --
    see sources.py's Party.fiscal_year docstring."""
    rows = [
        *_rows(("1", "City of Lincoln", "City of Lincoln", "contracts", 3, 100.0, "")),
        _budget_row("1", "City of Lincoln", 5, 114414798.89, "2025-2026"),
    ]
    index = build_full_index(rows)
    assert index[0][INDEX_COLUMNS.index("budget_amt")] == 114414798.89
    assert index[0][INDEX_COLUMNS.index("budget_recs")] == 5
    assert index[0][INDEX_COLUMNS.index("budget_fy")] == "2025-2026"


def test_non_budget_entity_has_zero_budget_totals():
    rows = _rows(("1", "ACME CO", "ACME CO", "contracts", 3, 100.0, ""))
    index = build_full_index(rows)
    assert index[0][INDEX_COLUMNS.index("budget_amt")] == 0
    assert index[0][INDEX_COLUMNS.index("budget_recs")] == 0
    assert index[0][INDEX_COLUMNS.index("budget_fy")] == ""


def test_budget_amount_is_not_summed_across_multiple_members():
    """Two budgets rows for the same entity (an edge case -- ordinarily there
    is exactly one) must keep only the LATEST fiscal year's amount, never add
    the two snapshots together."""
    rows = [
        _budget_row("1", "City of Lincoln", 3, 90000.0, "2023-2024"),
        _budget_row("1", "City of Lincoln", 2, 100000.0, "2025-2026"),
    ]
    index = build_full_index(rows)
    assert index[0][INDEX_COLUMNS.index("budget_amt")] == 100000.0
    assert index[0][INDEX_COLUMNS.index("budget_fy")] == "2025-2026"


CANONICAL_HEADER = [
    "entity_id", "canonical_name", "alias", "normalized_key", "source", "era",
    "role", "entity_type", "records", "amount", "source_id", "fiscal_year", "source_url",
]


def _write_canonical(tmp_path, *rows):
    path = tmp_path / "canonical_entities.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CANONICAL_HEADER)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_lobbying_member_gives_the_inline_entity_a_lobby_id(tmp_path, monkeypatch):
    """The join key for fetching ../ne-lobbying/d/positions.json client-side --
    same source_id build/build_entities.py already writes per member."""
    monkeypatch.setattr(build_site, "DATA_DIR", tmp_path)
    _write_canonical(
        tmp_path,
        {
            "entity_id": "1", "canonical_name": "ACME CO", "alias": "ACME CO",
            "normalized_key": "acme co", "source": "contracts", "era": "modern",
            "role": "vendor", "entity_type": "organization", "records": "1",
            "amount": "100.0", "source_id": "", "source_url": "",
        },
        {
            "entity_id": "1", "canonical_name": "ACME CO", "alias": "ACME CO",
            "normalized_key": "acme co", "source": "lobbying", "era": "modern",
            "role": "principal", "entity_type": "organization", "records": "3",
            "amount": "0", "source_id": "2285", "source_url": "",
        },
    )

    entities = build_site.build_entities()

    assert entities[0]["lobby_id"] == "2285"


def test_non_lobbying_entity_has_empty_lobby_id_inline(tmp_path, monkeypatch):
    monkeypatch.setattr(build_site, "DATA_DIR", tmp_path)
    _write_canonical(
        tmp_path,
        {
            "entity_id": "1", "canonical_name": "ACME CO", "alias": "ACME CO",
            "normalized_key": "acme co", "source": "contracts", "era": "modern",
            "role": "vendor", "entity_type": "organization", "records": "1",
            "amount": "100.0", "source_id": "", "source_url": "",
        },
        {
            "entity_id": "1", "canonical_name": "ACME CO", "alias": "ACME CO",
            "normalized_key": "acme co", "source": "campaign_finance", "era": "modern",
            "role": "contributor", "entity_type": "organization", "records": "1",
            "amount": "50.0", "source_id": "", "source_url": "",
        },
    )

    entities = build_site.build_entities()

    assert entities[0]["lobby_id"] == ""


def test_budget_entity_gets_fiscal_year_on_inline_object(tmp_path, monkeypatch):
    monkeypatch.setattr(build_site, "DATA_DIR", tmp_path)
    _write_canonical(
        tmp_path,
        {
            "entity_id": "1", "canonical_name": "City of Lincoln", "alias": "City of Lincoln",
            "normalized_key": "city of lincoln", "source": "contracts", "era": "modern",
            "role": "vendor", "entity_type": "organization", "records": "1",
            "amount": "100.0", "source_id": "", "fiscal_year": "", "source_url": "",
        },
        {
            "entity_id": "1", "canonical_name": "City of Lincoln", "alias": "Lincoln",
            "normalized_key": "city of lincoln", "source": "budgets", "era": "modern",
            "role": "subdivision", "entity_type": "organization", "records": "5",
            "amount": "114414798.89", "source_id": "", "fiscal_year": "2025-2026", "source_url": "",
        },
    )

    entities = build_site.build_entities()

    assert entities[0]["budget_fiscal_year"] == "2025-2026"
    assert entities[0]["totals"]["budgets"] == {"records": 5, "amount": 114414798.89}


def test_non_budget_entity_has_no_budget_totals_inline(tmp_path, monkeypatch):
    monkeypatch.setattr(build_site, "DATA_DIR", tmp_path)
    _write_canonical(
        tmp_path,
        {
            "entity_id": "1", "canonical_name": "ACME CO", "alias": "ACME CO",
            "normalized_key": "acme co", "source": "contracts", "era": "modern",
            "role": "vendor", "entity_type": "organization", "records": "1",
            "amount": "100.0", "source_id": "", "fiscal_year": "", "source_url": "",
        },
        {
            "entity_id": "1", "canonical_name": "ACME CO", "alias": "ACME CO",
            "normalized_key": "acme co", "source": "campaign_finance", "era": "modern",
            "role": "contributor", "entity_type": "organization", "records": "1",
            "amount": "50.0", "source_id": "", "fiscal_year": "", "source_url": "",
        },
    )

    entities = build_site.build_entities()

    assert entities[0]["budget_fiscal_year"] == ""
    assert "budgets" not in entities[0]["totals"]


def test_budget_amount_is_not_summed_across_multiple_members_inline(tmp_path, monkeypatch):
    """Same guard as the lazy-index version -- an entity with more than one
    budgets member (an edge case) keeps only the latest fiscal year's amount.
    A third, non-budgets member makes this a genuine cross-source entity --
    build_entities() only inlines entities with 2+ distinct sources; a
    budgets-only entity (however many members) lives in the lazy index
    instead, covered by the build_full_index() version of this test."""
    monkeypatch.setattr(build_site, "DATA_DIR", tmp_path)
    _write_canonical(
        tmp_path,
        {
            "entity_id": "1", "canonical_name": "City of Lincoln", "alias": "City of Lincoln",
            "normalized_key": "city of lincoln", "source": "contracts", "era": "modern",
            "role": "vendor", "entity_type": "organization", "records": "1",
            "amount": "500.0", "source_id": "", "fiscal_year": "", "source_url": "",
        },
        {
            "entity_id": "1", "canonical_name": "City of Lincoln", "alias": "Lincoln",
            "normalized_key": "city of lincoln", "source": "budgets", "era": "modern",
            "role": "subdivision", "entity_type": "organization", "records": "3",
            "amount": "90000.0", "source_id": "", "fiscal_year": "2023-2024", "source_url": "",
        },
        {
            "entity_id": "1", "canonical_name": "City of Lincoln", "alias": "Lincoln",
            "normalized_key": "city of lincoln", "source": "budgets", "era": "modern",
            "role": "subdivision", "entity_type": "organization", "records": "2",
            "amount": "100000.0", "source_id": "", "fiscal_year": "2025-2026", "source_url": "",
        },
    )

    entities = build_site.build_entities()

    assert entities[0]["totals"]["budgets"]["amount"] == 100000.0
    assert entities[0]["budget_fiscal_year"] == "2025-2026"


def test_retrieval_dates_includes_budgets_note(tmp_path, monkeypatch):
    """nebraska-budget-data ships no scrape_meta.json of its own (it's a
    third-party repo this project doesn't own) -- the date comes from that
    repo's own git history instead, and the page must say this is a one-shot
    snapshot, not a recurring pull."""
    import subprocess

    root = tmp_path / "ne-connect"
    root.mkdir()
    budget_repo = tmp_path / "nebraska-budget-data"
    budget_repo.mkdir()
    (budget_repo / "nebraska_budgets_all.csv").write_text("county_name\n")
    subprocess.run(["git", "init", "-q"], cwd=budget_repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=budget_repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=budget_repo, check=True)
    subprocess.run(["git", "add", "nebraska_budgets_all.csv"], cwd=budget_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "add budgets"], cwd=budget_repo, check=True)
    monkeypatch.setattr(build_site, "ROOT", root)

    dates = retrieval_dates()

    assert "budgets" in dates
    assert len(dates["budgets"]) == 10  # YYYY-MM-DD
    assert "one-shot snapshot" in dates["budgets_note"]


def test_retrieval_dates_no_budgets_note_when_repo_missing(tmp_path, monkeypatch):
    root = tmp_path / "ne-connect"
    root.mkdir()
    monkeypatch.setattr(build_site, "ROOT", root)

    dates = retrieval_dates()

    assert "budgets" not in dates
    assert "budgets_note" not in dates


def test_retrieval_dates_notes_missing_indiv_pull(tmp_path, monkeypatch):
    """committees/candidates are loaded but individual contributions are
    not (indiv24.zip deliberately not pulled) -- the page must say so rather
    than let a $0/empty column imply nothing was found."""
    root = tmp_path / "ne-connect"
    root.mkdir()
    fec_dir = tmp_path / "ne-fec" / "data"
    fec_dir.mkdir(parents=True)
    (fec_dir / "scrape_meta.json").write_text(
        json.dumps({"2024": {
            "cm": {"retrieved_at": "2026-09-15T06:01:16Z"},
            "cn": {"retrieved_at": "2026-09-15T06:01:13Z"},
        }})
    )
    monkeypatch.setattr(build_site, "ROOT", root)

    dates = retrieval_dates()

    assert dates["fec"] == "2026-09-15"
    assert "indiv24.zip" in dates["fec_note"]


def test_retrieval_dates_no_note_once_indiv_pulled(tmp_path, monkeypatch):
    root = tmp_path / "ne-connect"
    root.mkdir()
    fec_dir = tmp_path / "ne-fec" / "data"
    fec_dir.mkdir(parents=True)
    (fec_dir / "scrape_meta.json").write_text(
        json.dumps({"2024": {
            "cm": {"retrieved_at": "2026-09-15T06:01:16Z"},
            "cn": {"retrieved_at": "2026-09-15T06:01:13Z"},
            "indiv": {"retrieved_at": "2026-09-16T00:00:00Z"},
        }})
    )
    monkeypatch.setattr(build_site, "ROOT", root)

    dates = retrieval_dates()

    assert "fec_note" not in dates


def test_retrieval_dates_ignores_non_dataset_shaped_keys(tmp_path, monkeypatch):
    """download_legacy.py's "legacy" key in ne-campaign-finance's
    scrape_meta.json is {source_url, sha256, retrieved_at, path, members} --
    not {year: [{"run_date": ...}]} like the modern extract datasets. This
    used to crash retrieval_dates() with "string indices must be integers"
    the moment "legacy" existed alongside "contributions"/"expenditures"."""
    root = tmp_path / "ne-connect"
    root.mkdir()
    finance_dir = tmp_path / "ne-campaign-finance" / "data"
    finance_dir.mkdir(parents=True)
    (finance_dir / "scrape_meta.json").write_text(
        json.dumps(
            {
                "contributions": {"2026": [{"run_date": "2026-09-08"}]},
                "expenditures": {"2026": [{"run_date": "2026-09-09"}]},
                "legacy": {
                    "source_url": "https://nebraska.gov/nadc_data/nadc_data.zip",
                    "sha256": "abc123",
                    "retrieved_at": "2026-09-12",
                    "path": "raw/legacy/2026-09-12",
                    "members": {"formc1.txt": 12345},
                },
            }
        )
    )
    monkeypatch.setattr(build_site, "ROOT", root)

    dates = retrieval_dates()

    assert dates["campaign_finance"] == "2026-09-09"
