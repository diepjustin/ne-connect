import json

import verify_payload

GOOD_SUMMARY = {
    "canonical_entities": 138817,
    "entities_in_two_or_more_sources": 2190,
    "vendor_keys": 54352,
    "contributor_keys": 56316,
    "lobbying_keys": 1295,
    "disclosure_filer_keys": 20,
    "fec_org_keys": 207,
    "fec_contributor_keys": 29125,
}


def _write_entities_json(tmp_path, rows, columns=("a", "b")):
    path = tmp_path / "entities.json"
    path.write_text(json.dumps({"columns": list(columns), "rows": rows}))
    return path


def test_healthy_build_with_no_previous_summary_passes(tmp_path):
    entities_json = _write_entities_json(tmp_path, [[1, 2], [3, 4]])
    problems = verify_payload.verify(
        GOOD_SUMMARY, None, entities_json_path=entities_json, fec_rows_path=tmp_path / "nope.json"
    )
    assert problems == []


def test_below_the_absolute_floor_is_rejected(tmp_path):
    entities_json = _write_entities_json(tmp_path, [[1, 2]])
    summary = dict(GOOD_SUMMARY, canonical_entities=100)
    problems = verify_payload.verify(
        summary, None, entities_json_path=entities_json, fec_rows_path=tmp_path / "nope.json"
    )
    assert any("below the floor" in p for p in problems)


def test_large_drop_from_previous_is_rejected(tmp_path):
    entities_json = _write_entities_json(tmp_path, [[1, 2]])
    previous = dict(GOOD_SUMMARY)
    summary = dict(GOOD_SUMMARY, canonical_entities=100_000)  # >10% drop from 138,817
    problems = verify_payload.verify(
        summary, previous, entities_json_path=entities_json, fec_rows_path=tmp_path / "nope.json"
    )
    assert any("dropped" in p and "canonical_entities" in p for p in problems)


def test_small_drop_from_previous_is_ordinary_drift(tmp_path):
    entities_json = _write_entities_json(tmp_path, [[1, 2]])
    previous = dict(GOOD_SUMMARY)
    summary = dict(GOOD_SUMMARY, canonical_entities=137_000)  # <1% drop
    problems = verify_payload.verify(
        summary, previous, entities_json_path=entities_json, fec_rows_path=tmp_path / "nope.json"
    )
    assert problems == []


def test_a_source_going_from_present_to_zero_is_rejected(tmp_path):
    entities_json = _write_entities_json(tmp_path, [[1, 2]])
    previous = dict(GOOD_SUMMARY)
    summary = dict(GOOD_SUMMARY, fec_contributor_keys=0)
    problems = verify_payload.verify(
        summary, previous, entities_json_path=entities_json, fec_rows_path=tmp_path / "nope.json"
    )
    assert any("fec_contributor_keys" in p and "0" in p for p in problems)


def test_a_source_that_was_already_zero_staying_zero_is_fine(tmp_path):
    entities_json = _write_entities_json(tmp_path, [[1, 2]])
    previous = dict(GOOD_SUMMARY, disclosure_filer_keys=0)
    summary = dict(GOOD_SUMMARY, disclosure_filer_keys=0)
    problems = verify_payload.verify(
        summary, previous, entities_json_path=entities_json, fec_rows_path=tmp_path / "nope.json"
    )
    assert problems == []


def test_missing_entities_json_is_rejected(tmp_path):
    problems = verify_payload.verify(
        GOOD_SUMMARY, None,
        entities_json_path=tmp_path / "does_not_exist.json",
        fec_rows_path=tmp_path / "nope.json",
    )
    assert any("does not exist" in p for p in problems)


def test_empty_rows_is_rejected(tmp_path):
    entities_json = _write_entities_json(tmp_path, [])
    problems = verify_payload.verify(
        GOOD_SUMMARY, None, entities_json_path=entities_json, fec_rows_path=tmp_path / "nope.json"
    )
    assert any("zero rows" in p for p in problems)


def test_row_width_mismatch_is_rejected(tmp_path):
    entities_json = _write_entities_json(tmp_path, [[1, 2], [1, 2, 3]])  # second row too wide
    problems = verify_payload.verify(
        GOOD_SUMMARY, None, entities_json_path=entities_json, fec_rows_path=tmp_path / "nope.json"
    )
    assert any("column header" in p for p in problems)


def test_suspiciously_small_fec_rows_file_is_rejected(tmp_path):
    entities_json = _write_entities_json(tmp_path, [[1, 2]])
    fec_rows = tmp_path / "fec_rows.json"
    fec_rows.write_text("{}")  # far under 1000 bytes
    problems = verify_payload.verify(
        GOOD_SUMMARY, None, entities_json_path=entities_json, fec_rows_path=fec_rows
    )
    assert any("suspiciously small" in p for p in problems)


def test_missing_fec_rows_file_is_not_a_problem(tmp_path):
    # FEC data is allowed to be entirely absent (e.g. before it's ever been
    # pulled) -- only a present-but-tiny file is suspicious.
    entities_json = _write_entities_json(tmp_path, [[1, 2]])
    problems = verify_payload.verify(
        GOOD_SUMMARY, None, entities_json_path=entities_json, fec_rows_path=tmp_path / "nope.json"
    )
    assert problems == []


def test_main_exits_nonzero_on_a_broken_build(tmp_path, monkeypatch, capsys):
    summary_path = tmp_path / "entities_summary.json"
    summary_path.write_text(json.dumps(dict(GOOD_SUMMARY, canonical_entities=1)))
    entities_json = _write_entities_json(tmp_path, [[1, 2]])
    monkeypatch.setattr(verify_payload, "SUMMARY_PATH", summary_path)
    monkeypatch.setattr(verify_payload, "ENTITIES_JSON_PATH", entities_json)
    monkeypatch.setattr(verify_payload, "FEC_ROWS_PATH", tmp_path / "nope.json")

    exit_code = verify_payload.main([])

    assert exit_code == 1
    assert "BUILD LOOKS BROKEN" in capsys.readouterr().err


def test_main_exits_zero_on_a_healthy_build(tmp_path, monkeypatch):
    summary_path = tmp_path / "entities_summary.json"
    summary_path.write_text(json.dumps(GOOD_SUMMARY))
    entities_json = _write_entities_json(tmp_path, [[1, 2]])
    monkeypatch.setattr(verify_payload, "SUMMARY_PATH", summary_path)
    monkeypatch.setattr(verify_payload, "ENTITIES_JSON_PATH", entities_json)
    monkeypatch.setattr(verify_payload, "FEC_ROWS_PATH", tmp_path / "nope.json")

    assert verify_payload.main([]) == 0
