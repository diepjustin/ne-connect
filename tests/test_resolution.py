import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "build"))

from index import TokenIndex, candidate_pairs  # noqa: E402
from match import match_pair, score_pair  # noqa: E402
from resolutions import DIFFERENT, SAME, Ledger, Resolution, UnionFind, pair_id  # noqa: E402
from review import record  # noqa: E402

# The names under test, plus filler. Filler is not padding: document
# frequency and IDF are corpus-relative, so a ten-name corpus makes every token
# look "common" (>2% share) and nothing behaves the way it does against the real
# 79,311 names. The filler restores realistic frequency ratios.
NAMES_UNDER_TEST = [
    "KIEWIT",
    "KIEWIT CORPORATION",
    "HAWKINS CONSTRUCTION",
    "HAWKINS SUPPLY",
    "SAMPSON CONSTRUCTION",
    "PAVERS",
    "J P MORGAN SECURITIES",
    "P J MORGAN",
]

FILLER = (
    [f"NEBRASKA SERVICES {n}" for n in range(60)]
    + [f"MIDWEST SUPPLY {n}" for n in range(60)]
    + [f"COUNTY CONSTRUCTION {n}" for n in range(60)]
)

CORPUS = NAMES_UNDER_TEST + FILLER


@pytest.fixture
def index():
    return TokenIndex(CORPUS)


# --- scoring -----------------------------------------------------------------


def test_identical_keys_score_one(index):
    score, reason = score_pair("KIEWIT", "KIEWIT", index)
    assert score == 1.0
    assert reason == "identical normalized key"


def test_rare_shared_token_beats_common_one(index):
    """Sharing HAWKINS should count for more than sharing NEBRASKA."""
    rare, _ = score_pair("HAWKINS CONSTRUCTION", "HAWKINS SUPPLY", index)
    common, _ = score_pair("NEBRASKA SERVICES", "NEBRASKA SUPPLY", index)
    assert rare > common


def test_score_carries_a_readable_reason(index):
    _, reason = score_pair("HAWKINS CONSTRUCTION", "HAWKINS SUPPLY", index)
    assert "'HAWKINS'" in reason
    assert "token overlap" in reason


def test_a_single_token_key_can_never_auto_merge(index):
    """KIEWIT == KIEWIT is a perfect string match and still gets a human.

    The auto floor is a multiple (>1) of the rarest-possible single token, so no
    one-token key clears it however rare it is. That is deliberate: rarity
    cannot separate a distinctive brand from an uncommon English word -- in the
    live data PAVERS scores a HIGHER idf than KIEWIT.
    """
    for name in ("KIEWIT", "PAVERS"):
        match = match_pair(name, name, index)
        assert match.score == 1.0
        assert match.decision == "review"
        assert match.kind == "identical_key"
        assert "too generic" in match.reason


def test_anything_involving_a_person_never_auto_merges(index):
    match = match_pair(
        "SAMPSON CONSTRUCTION", "SAMPSON CONSTRUCTION", index,
        left_type="organization", right_type="individual",
    )
    assert match.score == 1.0
    assert match.decision == "review"
    assert "involves a person" in match.reason


def test_distinctive_multi_token_org_auto_accepts(index):
    match = match_pair("HAWKINS CONSTRUCTION", "HAWKINS CONSTRUCTION", index)
    assert match.decision == "auto"


def test_jp_morgan_is_not_pj_morgan(index):
    """The false positive that justifies the whole review step.

    Same tokens, different order, $647M at stake, and two unrelated companies:
    a Wall Street bank and an Omaha real estate firm. Scoring cannot tell them
    apart, so it must not be allowed to decide.
    """
    match = match_pair("J P MORGAN SECURITIES", "P J MORGAN", index)
    assert match.decision != "auto"


# --- blocking ----------------------------------------------------------------


def test_blocking_finds_the_real_pair_without_comparing_everything(index):
    pairs = list(candidate_pairs(["KIEWIT"], CORPUS, index))
    rights = {right for _, right in pairs}
    assert "KIEWIT" in rights
    assert "KIEWIT CORPORATION" in rights
    assert "PAVERS" not in rights  # shares no token, never scored


def test_common_tokens_are_skipped(index):
    # NEBRASKA appears in 60 of 188 names, far over the 2% share cap, so it is
    # never used as a blocking key -- otherwise it would build one huge block.
    assert "NEBRASKA" in index.common_tokens
    assert "KIEWIT" not in index.common_tokens


# --- the ledger --------------------------------------------------------------


def test_pair_id_ignores_order():
    assert pair_id("A", "B") == pair_id("B", "A")


def test_decision_requires_an_owner():
    with pytest.raises(ValueError):
        Resolution(left_key="A", right_key="B", decision=SAME, decided_by="")


def test_decision_must_be_same_or_different():
    with pytest.raises(ValueError):
        Resolution(left_key="A", right_key="B", decision="maybe", decided_by="jdiep")


def test_human_decision_overrides_the_scorer(index):
    ledger = Ledger([
        Resolution(
            left_key="J P MORGAN SECURITIES", right_key="P J MORGAN",
            decision=DIFFERENT, decided_by="jdiep", note="unrelated firms",
        )
    ])
    match = ledger.apply(match_pair("HAWKINS CONSTRUCTION", "HAWKINS CONSTRUCTION", index))
    assert match.decision == "auto"  # untouched pairs flow through normally

    ruled = ledger.apply(match_pair("J P MORGAN SECURITIES", "P J MORGAN", index))
    assert ruled.decision == "rejected"
    assert "human decision on record" in ruled.reason


def test_ledger_survives_a_round_trip(tmp_path):
    path = tmp_path / "resolutions.csv"
    ledger = Ledger([
        Resolution(left_key="B KEY", right_key="A KEY", decision=SAME, decided_by="jdiep")
    ])
    ledger.save(path)
    reloaded = Ledger.load(path)
    assert len(reloaded) == 1
    assert reloaded.decision_for("A KEY", "B KEY") == SAME


def test_review_cli_refuses_a_model_as_decider(tmp_path):
    """The ledger's value is that a person stands behind each row."""
    for name in ("claude", "gpt-4", "some-llm", "autobot"):
        with pytest.raises(ValueError, match="must name a person"):
            record("A KEY", "B KEY", SAME, name, ledger_path=tmp_path / "r.csv")

    ledger = record(
        "A KEY", "B KEY", SAME, "jdiep",
        note="checked SoS filings", suggested_by="claude", suggested_score="0.97",
        ledger_path=tmp_path / "r.csv",
    )
    assert ledger.decision_for("A KEY", "B KEY") == SAME


# --- clustering --------------------------------------------------------------


def test_union_find_groups_transitively():
    clusters = UnionFind()
    clusters.union("A", "B")
    clusters.union("B", "C")
    clusters.union("X", "Y")
    groups = clusters.groups()
    assert len(groups) == 2
    assert {"A", "B", "C"} in [set(g) for g in groups.values()]


def test_entity_ids_are_stable_regardless_of_merge_order():
    """A published entity URL must not change when the data grows."""
    first, second = UnionFind(), UnionFind()
    first.union("A", "B")
    first.union("C", "A")
    second.union("C", "B")
    second.union("B", "A")
    assert set(first.groups()) == set(second.groups()) == {"A"}
