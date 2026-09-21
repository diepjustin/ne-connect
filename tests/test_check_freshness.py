from datetime import date

import pytest

import check_freshness as cf

TODAY = date(2026, 9, 21)

FRESH = {
    "contracts": "ne-contracts-hub-data-2026-09-20",
    "campaign_finance": "ne-campaign-finance-data-2026-09-20",
    "fec": "ne-fec-data-2026-09-20",
    "lobbying": "lobbying-data-2026-09-14",
}


def test_tag_date_reads_the_trailing_iso_date():
    assert cf.tag_date("ne-contracts-hub-data-2026-09-20") == date(2026, 9, 20)
    assert cf.tag_date("lobbying-data-2026-09-14") == date(2026, 9, 14)


def test_tag_date_is_none_for_undated_or_impossible_tags():
    assert cf.tag_date("v1.2.3") is None
    assert cf.tag_date("") is None
    assert cf.tag_date("ne-fec-data-2026-13-40") is None


def test_every_release_within_cadence_is_clean():
    warnings, failures = cf.check(FRESH, TODAY)
    assert warnings == []
    assert failures == []


def test_a_release_cut_after_today_counts_as_zero_days_old():
    """The tag date is America/Chicago and the runner compares in UTC, so a
    release can legitimately look like it's from 'tomorrow'."""
    tags = dict(FRESH, contracts="ne-contracts-hub-data-2026-09-22")
    warnings, failures = cf.check(tags, TODAY)
    assert warnings == [] and failures == []


def test_one_missed_night_is_a_warning_not_a_failure():
    tags = dict(FRESH, contracts="ne-contracts-hub-data-2026-09-16")  # 5 days
    warnings, failures = cf.check(tags, TODAY)
    assert failures == []
    assert len(warnings) == 1 and warnings[0].startswith("contracts:")


def test_a_week_of_silence_from_a_nightly_source_fails():
    tags = dict(FRESH, campaign_finance="ne-campaign-finance-data-2026-09-10")  # 11 days
    warnings, failures = cf.check(tags, TODAY)
    assert len(failures) == 1 and failures[0].startswith("campaign_finance:")


def test_monthly_lobbying_release_is_not_stale_at_five_weeks():
    tags = dict(FRESH, lobbying="lobbying-data-2026-08-17")  # 35 days
    warnings, failures = cf.check(tags, TODAY)
    assert warnings == [] and failures == []


def test_monthly_lobbying_release_warns_past_forty_days_and_fails_past_seventy():
    warn_tags = dict(FRESH, lobbying="lobbying-data-2026-08-01")   # 51 days
    fail_tags = dict(FRESH, lobbying="lobbying-data-2026-07-01")   # 82 days
    assert cf.check(warn_tags, TODAY)[0] and not cf.check(warn_tags, TODAY)[1]
    assert cf.check(fail_tags, TODAY)[1]


def test_missing_source_is_a_failure_not_silently_skipped():
    tags = {k: v for k, v in FRESH.items() if k != "fec"}
    warnings, failures = cf.check(tags, TODAY)
    assert any(f.startswith("fec: no release found") for f in failures)


def test_undated_tag_fails_loudly_rather_than_passing():
    tags = dict(FRESH, fec="ne-fec-data-latest")
    warnings, failures = cf.check(tags, TODAY)
    assert any("no YYYY-MM-DD suffix" in f for f in failures)


def test_main_exit_code_and_annotations(capsys):
    argv = [f"--tag={k}={v}" for k, v in FRESH.items()] + ["--today", "2026-09-21"]
    assert cf.main(argv) == 0
    out = capsys.readouterr().out
    assert "within its cadence" in out
    assert "::warning::" not in out

    stale = [f"--tag={k}={v}" for k, v in dict(FRESH, contracts="ne-contracts-hub-data-2026-09-01").items()]
    assert cf.main(stale + ["--today", "2026-09-21"]) == 1
    captured = capsys.readouterr()
    assert "::error::contracts:" in captured.err


def test_main_rejects_an_unknown_source_name():
    with pytest.raises(SystemExit):
        cf.main(["--tag", "budgets=x-2026-09-20"])
