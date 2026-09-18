"""Structural checks on ne-connect-nightly.yml -- a YAML-shape test, not a
live run. This project has no way to execute GitHub Actions locally, so this
guards the specific invariants that have bitten sibling repos before: the
DST dual-cron gate, never cancelling a half-done deploy, and the
push/workflow_dispatch always-proceed branch this workflow's gate step needs
that a plain copy of the dual-cron pattern wouldn't have.
"""

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ne-connect-nightly.yml"


def _load():
    # PyYAML parses the bare `on:` key as the boolean True, not the string
    # "on" -- both need looking up.
    return yaml.safe_load(WORKFLOW_PATH.read_text())


def test_workflow_file_exists_and_parses():
    workflow = _load()
    assert workflow["name"] == "NE Connect nightly rebuild"


def test_two_dst_cron_entries():
    workflow = _load()
    schedule = workflow[True]["schedule"]
    crons = [entry["cron"] for entry in schedule]
    assert len(crons) == 2
    assert len(set(crons)) == 2  # genuinely two different times, not a copy-paste dupe


def test_triggers_on_push_and_workflow_dispatch_too():
    workflow = _load()
    triggers = workflow[True]
    assert "push" in triggers
    assert "workflow_dispatch" in triggers
    assert triggers["push"]["branches"] == ["main"]


def test_deploy_never_cancels_a_half_done_run():
    workflow = _load()
    assert workflow["concurrency"]["cancel-in-progress"] is False


def test_gate_step_special_cases_non_schedule_events():
    """Without this, github.event.schedule is empty on push/workflow_dispatch
    and the dual-cron gate would incorrectly skip every non-scheduled run."""
    workflow = _load()
    gate_step = next(
        s for s in workflow["jobs"]["build"]["steps"] if s.get("id") == "gate"
    )
    assert '$EVENT" != \'schedule\'' in gate_step["run"]


def test_deploy_job_is_gated_on_build_proceeding_and_not_dry_run():
    workflow = _load()
    deploy = workflow["jobs"]["deploy"]
    condition = deploy["if"]
    assert "needs.build.outputs.proceed == 'true'" in condition
    assert "dry_run" in condition


def test_pages_permissions_present_for_artifact_deploy():
    workflow = _load()
    permissions = workflow["permissions"]
    assert permissions["pages"] == "write"
    assert permissions["id-token"] == "write"
