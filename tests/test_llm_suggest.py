import json

import llm_suggest
from resolutions import pair_id

ROW = {
    "left_key": "SMITH JOHN",
    "right_key": "SMITH JOHN OTHER",
    "vendor_names": "SMITH, JOHN",
    "contributor_names": "SMITH, JOHN",
    "left_source": "campaign_finance",
    "right_source": "fec",
    "left_cities": "OMAHA",
    "right_cities": "LINCOLN",
    "match_kind": "fuzzy",
    "score": "0.72",
    "reason": "shares 2 token(s), rarest 'SMITH'",
}


def _fake_generate(response_text):
    def generate(prompt, model):
        return response_text
    return generate


# --- build_prompt --------------------------------------------------------


def test_build_prompt_includes_the_row_fields_not_outside_facts():
    prompt = llm_suggest.build_prompt(ROW)
    assert "SMITH, JOHN" in prompt
    assert "OMAHA" in prompt
    assert "LINCOLN" in prompt
    assert "fuzzy" in prompt
    assert "SMITH" in prompt  # from reason


def test_build_prompt_labels_untracked_cities():
    row = dict(ROW, left_cities="", right_cities="")
    prompt = llm_suggest.build_prompt(row)
    assert "(not tracked)" in prompt


# --- suggest_pair ----------------------------------------------------------


def test_suggest_pair_well_formed_response():
    generate = _fake_generate(json.dumps({
        "decision": "different", "confidence": 0.81,
        "reasoning": "Different cities and no other corroborating link.",
    }))
    result = llm_suggest.suggest_pair(ROW, generate=generate)
    assert result["pair_id"] == pair_id(ROW["left_key"], ROW["right_key"])
    assert result["decision"] == "different"
    assert result["confidence"] == 0.81
    assert "Different cities" in result["reasoning"]
    assert "error" not in result


def test_suggest_pair_confidence_is_clamped():
    generate = _fake_generate(json.dumps({
        "decision": "same", "confidence": 4.2, "reasoning": "Overconfident test case.",
    }))
    result = llm_suggest.suggest_pair(ROW, generate=generate)
    assert result["confidence"] == 1.0


def test_suggest_pair_malformed_json_is_an_error_not_a_crash():
    generate = _fake_generate("not json at all")
    result = llm_suggest.suggest_pair(ROW, generate=generate)
    assert "error" in result
    assert result["pair_id"] == pair_id(ROW["left_key"], ROW["right_key"])


def test_suggest_pair_unexpected_decision_value_is_an_error():
    generate = _fake_generate(json.dumps({
        "decision": "maybe", "confidence": 0.5, "reasoning": "x",
    }))
    result = llm_suggest.suggest_pair(ROW, generate=generate)
    assert "error" in result


def test_suggest_pair_empty_reasoning_is_an_error():
    generate = _fake_generate(json.dumps({
        "decision": "same", "confidence": 0.9, "reasoning": "",
    }))
    result = llm_suggest.suggest_pair(ROW, generate=generate)
    assert "error" in result


def test_suggest_pair_generate_exception_is_an_error():
    def generate(prompt, model):
        raise TimeoutError("model took too long")
    result = llm_suggest.suggest_pair(ROW, generate=generate)
    assert "error" in result
    assert "took too long" in result["error"]


# --- checkpoint --------------------------------------------------------


def test_checkpoint_round_trips(tmp_path):
    path = tmp_path / "llm_suggestions.jsonl"
    records = [
        {"pair_id": "abc123", "decision": "same"},
        {"pair_id": "def456", "decision": "different"},
    ]
    llm_suggest.append_checkpoint(records, path=path)
    loaded = llm_suggest.load_checkpoint(path=path)
    assert set(loaded) == {"abc123", "def456"}
    assert loaded["abc123"]["decision"] == "same"


def test_checkpoint_last_entry_wins(tmp_path):
    path = tmp_path / "llm_suggestions.jsonl"
    llm_suggest.append_checkpoint([{"pair_id": "abc123", "decision": "same"}], path=path)
    llm_suggest.append_checkpoint([{"pair_id": "abc123", "decision": "different"}], path=path)
    loaded = llm_suggest.load_checkpoint(path=path)
    assert loaded["abc123"]["decision"] == "different"


def test_checkpoint_recovers_from_a_truncated_trailing_line(tmp_path):
    path = tmp_path / "llm_suggestions.jsonl"
    good_line = json.dumps({"pair_id": "abc123", "decision": "same"})
    path.write_text(good_line + "\n" + '{"pair_id": "broken", "decisi')

    loaded = llm_suggest.load_checkpoint(path=path)

    assert set(loaded) == {"abc123"}
    # The partial line was truncated off disk, not left corrupting the file.
    assert path.read_text() == good_line + "\n"


def test_missing_checkpoint_file_is_empty_not_an_error(tmp_path):
    assert llm_suggest.load_checkpoint(path=tmp_path / "nope.jsonl") == {}


# --- todo / type combo ------------------------------------------------------


def test_todo_skips_cached_pairs_but_retries_errors():
    ok_pid = pair_id("A KEY", "B KEY")
    error_pid = pair_id("C KEY", "D KEY")
    rows = [
        {"left_key": "A KEY", "right_key": "B KEY"},
        {"left_key": "C KEY", "right_key": "D KEY"},
        {"left_key": "E KEY", "right_key": "F KEY"},
    ]
    checkpoint = {
        ok_pid: {"pair_id": ok_pid, "decision": "same"},
        error_pid: {"pair_id": error_pid, "error": "timeout"},
    }
    todo = llm_suggest._todo(rows, checkpoint)
    todo_keys = {(r["left_key"], r["right_key"]) for r in todo}
    assert todo_keys == {("C KEY", "D KEY"), ("E KEY", "F KEY")}


def test_type_combo():
    assert llm_suggest._type_combo({"left_type": "organization", "right_type": "organization"}) == "organization"
    assert llm_suggest._type_combo({"left_type": "individual", "right_type": "individual"}) == "individual"
    assert llm_suggest._type_combo({"left_type": "organization", "right_type": "individual"}) == "mixed"


# --- --status prints without any network call -------------------------------


def test_status_flag_makes_no_network_call(tmp_path, monkeypatch, capsys):
    queue_path = tmp_path / "review_queue.csv"
    queue_path.write_text(
        "left_key,right_key,left_type,right_type\n"
        "A KEY,B KEY,organization,organization\n"
    )
    monkeypatch.setattr(llm_suggest, "QUEUE_PATH", queue_path)
    monkeypatch.setattr(llm_suggest, "CACHE_PATH", tmp_path / "llm_suggestions.jsonl")

    def _no_network(*a, **k):
        raise AssertionError("must not touch the network for --status")
    monkeypatch.setattr(llm_suggest, "ollama_available", _no_network)
    monkeypatch.setattr(llm_suggest, "ollama_generate", _no_network)

    exit_code = llm_suggest.main(["--status"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "TODO=1" in out
