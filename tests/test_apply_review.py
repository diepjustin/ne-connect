import csv

import apply_review
from resolutions import Ledger, pair_id

DECISIONS = """left_key,right_key,decision,note
acme co,acme company,same,obvious typo
smith jane,smith jane other,different,two different donors
"""


def _write_decisions(tmp_path, text=DECISIONS):
    path = tmp_path / "decisions.csv"
    path.write_text(text)
    return path


def test_applies_same_and_different_decisions_to_a_fresh_ledger(tmp_path):
    decisions_path = _write_decisions(tmp_path)
    ledger_path = tmp_path / "resolutions.csv"

    exit_code = apply_review.main(
        [str(decisions_path), "--by", "diep", "--ledger", str(ledger_path)]
    )

    assert exit_code == 0
    ledger = Ledger.load(ledger_path)
    assert len(ledger) == 2
    assert ledger.decision_for("acme co", "acme company") == "same"
    assert ledger.decision_for("smith jane", "smith jane other") == "different"


def test_decided_by_and_suggested_by_are_recorded(tmp_path):
    decisions_path = _write_decisions(tmp_path)
    ledger_path = tmp_path / "resolutions.csv"

    apply_review.main([str(decisions_path), "--by", "diep", "--ledger", str(ledger_path)])

    with ledger_path.open(newline="") as fh:
        rows = {r["pair_id"]: r for r in csv.DictReader(fh)}
    row = rows[pair_id("acme co", "acme company")]
    assert row["decided_by"] == "diep"
    assert row["suggested_by"] == "review"
    assert row["note"] == "obvious typo"


def test_rerunning_the_same_export_is_idempotent_not_duplicated(tmp_path):
    decisions_path = _write_decisions(tmp_path)
    ledger_path = tmp_path / "resolutions.csv"

    apply_review.main([str(decisions_path), "--by", "diep", "--ledger", str(ledger_path)])
    apply_review.main([str(decisions_path), "--by", "diep", "--ledger", str(ledger_path)])

    ledger = Ledger.load(ledger_path)
    assert len(ledger) == 2


def test_unrecognized_decision_value_is_skipped_not_crashed(tmp_path):
    decisions_path = _write_decisions(
        tmp_path,
        "left_key,right_key,decision,note\nfoo,bar,skip,\n",
    )
    ledger_path = tmp_path / "resolutions.csv"

    apply_review.main([str(decisions_path), "--by", "diep", "--ledger", str(ledger_path)])

    ledger = Ledger.load(ledger_path)
    assert len(ledger) == 0
