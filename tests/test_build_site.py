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
