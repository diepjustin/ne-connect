"""Generate LLM-suggested same/different decisions for data/review_queue.csv.

A triage aid, not a decision-maker: CLAUDE.md rule 4 stands -- "No entity is
merged on a judgement call without a recorded human decision." Nothing this
script produces reaches data/manual/resolutions.csv on its own. It only
writes pipeline/llm_suggestions.jsonl, a local, gitignored cache that
build/build_review_tool.py reads to show a suggestion in the review page's
detail view -- a human still has to click Same/Different themselves.

Uses a local model via Ollama (llama3.1:8b-instruct-q4_K_M), not a paid API,
same pattern as ../ne-contracts/scripts/generate_ai_summaries.py:
    brew install ollama
    ollama serve &
    ollama pull llama3.1:8b-instruct-q4_K_M

Same append-only, skip-what's-done checkpoint shape as that script, keyed on
resolutions.pair_id() instead of a document token -- a pair already cached
(and not marked "error") is never re-asked, so repeat runs only pay for new
work. A cached "error" record is retried, not treated as done: this is a
triage aid over real money/identity guesses, and silently treating a timeout
as "processed" would quietly starve the review queue of a suggestion it
should have gotten.

    python3 resolve/llm_suggest.py --status
    python3 resolve/llm_suggest.py --limit 100 --kind organization
    python3 resolve/llm_suggest.py
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from resolutions import pair_id

ROOT = Path(__file__).resolve().parent.parent
QUEUE_PATH = ROOT / "data" / "review_queue.csv"
# Not under data/ -- that whole tree is rebuilt from scratch by every
# build_entities.py run, and this cache is expensive (real model calls) to
# regenerate. pipeline/ is already the established gitignored, local-only
# home for sensitive raw candidate data (see .gitignore's pipeline/ entry);
# this cache is the same sensitivity class, holding a model's guesses about
# whether two named individuals are the same person.
CACHE_PATH = ROOT / "pipeline" / "llm_suggestions.jsonl"

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.1:8b-instruct-q4_K_M"

# Benchmarked on this machine 2026-09-17, 20-pair organization slices:
# workers=2 -> 0.14/s (143s), workers=4 -> 0.18/s (113s) -- compute-bound
# local inference, not I/O-bound, so concurrency buys only ~28% past 2, not
# a linear speedup. 4 is the plateau found so far, not a hard ceiling --
# re-benchmark with --workers if this runs on different hardware.
DEFAULT_WORKERS = 4

CHECKPOINT_EVERY = 20

ALLOWED_DECISIONS = ("same", "different", "uncertain")

PROMPT_TEMPLATE = """You are helping a journalist review candidate entity matches for a Nebraska public-records database. Two names, each from a different public dataset, may or may not refer to the same real-world person or organization. Decide using ONLY the information given below -- do not assume anything not stated here.

Left ({left_source}): {vendor_names}
Right ({right_source}): {contributor_names}
Left city/cities on record: {left_cities}
Right city/cities on record: {right_cities}
Automated match type: {match_kind} (score {score})
Automated match reasoning: {reason}

Respond with a single JSON object with exactly these three keys:
  "decision": one of "same", "different", or "uncertain"
  "confidence": a number from 0 to 1
  "reasoning": one short, factual sentence citing only the information above

Prefer "uncertain" over guessing whenever these could plausibly be different
people or organizations -- a missed match costs a reviewer a few extra
seconds, but a wrong "same" could merge two different people's records. This
caution matters most when both sides are individual people: common names and
small towns produce frequent coincidental name matches that are NOT the same
person. Never state or imply that either party did anything improper --
you are only judging whether these are the same real-world entity.

Respond with the JSON object only, no other text."""


def ollama_available() -> bool:
    try:
        urllib.request.urlopen("http://localhost:11434/api/version", timeout=5)
        return True
    except (urllib.error.URLError, OSError):
        return False


def build_prompt(row: dict) -> str:
    return PROMPT_TEMPLATE.format(
        left_source=row.get("left_source", ""),
        vendor_names=row.get("vendor_names", ""),
        right_source=row.get("right_source", ""),
        contributor_names=row.get("contributor_names", ""),
        left_cities=row.get("left_cities") or "(not tracked)",
        right_cities=row.get("right_cities") or "(not tracked)",
        match_kind=row.get("match_kind", ""),
        score=row.get("score", ""),
        reason=row.get("reason", ""),
    )


def ollama_generate(prompt: str, model: str) -> str:
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        # 300 confirmed sufficient: 40 real pairs on 2026-09-17 (organization
        # slice, --workers 2 and 4) produced zero truncated-JSON errors.
        "options": {"temperature": 0.2, "num_predict": 300},
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())["response"]


def suggest_pair(row: dict, *, model: str = MODEL, generate=ollama_generate) -> dict:
    """Ask the model about one review_queue.csv row; never raises.

    `generate` is injectable so tests never touch the network -- pass a fake
    callable(prompt, model) -> str.
    """
    left_key, right_key = row["left_key"], row["right_key"]
    pid = pair_id(left_key, right_key)
    prompt = build_prompt(row)
    t0 = time.time()
    try:
        raw = generate(prompt, model)
    except Exception as e:
        return {"pair_id": pid, "left_key": left_key, "right_key": right_key,
                "model": model, "error": str(e)[:200]}

    seconds = round(time.time() - t0, 2)
    try:
        parsed = json.loads(raw)
        decision = str(parsed.get("decision", "")).strip().lower()
        if decision not in ALLOWED_DECISIONS:
            raise ValueError(f"unexpected decision {decision!r}")
        confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0))))
        reasoning = str(parsed.get("reasoning", "")).strip()
        if not reasoning:
            raise ValueError("empty reasoning")
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        return {"pair_id": pid, "left_key": left_key, "right_key": right_key,
                "model": model, "error": f"bad response: {e}"[:200],
                "raw": raw[:500]}

    return {
        "pair_id": pid,
        "left_key": left_key,
        "right_key": right_key,
        "model": model,
        "decision": decision,
        "confidence": confidence,
        "reasoning": reasoning,
        "prompt_hash": hashlib.sha256(prompt.encode()).hexdigest()[:16],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "seconds": seconds,
    }


def load_queue_rows(path: Path = QUEUE_PATH) -> list[dict]:
    if not path.exists():
        raise SystemExit(f"missing {path} -- run build/build_entities.py first")
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_checkpoint(path: Path = CACHE_PATH) -> dict:
    """{pair_id: record}, last entry wins -- same recovery shape as
    ne-contracts/scripts/generate_ai_summaries.py's load_checkpoint()."""
    store: dict = {}
    if not path.exists():
        return store
    with path.open("rb") as f:
        raw = f.readlines()
    offset = 0
    for i, blob in enumerate(raw):
        start, offset = offset, offset + len(blob)
        line = blob.decode("utf-8", "replace").strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            if i != len(raw) - 1:
                raise
            print(f"    Note: {path} ends mid-write; truncating {len(blob)} bytes "
                  "of a partial line. That pair is simply retried.")
            os.truncate(path, start)
            break
        store[rec["pair_id"]] = rec
    return store


def append_checkpoint(records: list, path: Path = CACHE_PATH) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        f.flush()


def _type_combo(row: dict) -> str:
    left, right = row.get("left_type", ""), row.get("right_type", "")
    return left if left == right else "mixed"


def _todo(rows: list, checkpoint: dict) -> list:
    todo = []
    for row in rows:
        cached = checkpoint.get(pair_id(row["left_key"], row["right_key"]))
        if cached is None or "error" in cached:
            todo.append(row)
    return todo


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS,
                         help=f"concurrent Ollama requests (default {DEFAULT_WORKERS}, "
                              "not yet benchmarked for this task -- measure before raising)")
    parser.add_argument("--status", action="store_true",
                         help="print progress and exit -- no model calls")
    parser.add_argument("--limit", type=int, default=None,
                         help="process at most N pairs this run")
    parser.add_argument("--kind", choices=("organization", "individual", "mixed"), default=None,
                         help="restrict to one entity-type combo; default is all rows. "
                              "'organization' is recommended for a first test batch -- "
                              "more reliable name-only signal than individual x individual.")
    args = parser.parse_args(argv)

    # QUEUE_PATH/CACHE_PATH looked up here (not via these functions' default
    # parameter values, which bind at def-time) so a test can monkeypatch
    # the module attribute and have main() actually see it.
    rows = load_queue_rows(QUEUE_PATH)
    if args.kind:
        rows = [r for r in rows if _type_combo(r) == args.kind]

    checkpoint = load_checkpoint(CACHE_PATH)
    todo = _todo(rows, checkpoint)

    if args.status:
        print(f"QUEUE_ROWS={len(rows):,}" + (f" (filtered to --kind {args.kind})" if args.kind else ""))
        print(f"CACHED={len(rows) - len(todo):,}  TODO={len(todo):,}")
        return 0

    if args.limit is not None:
        todo = todo[:args.limit]

    if not todo:
        print("Nothing to do -- every matching row already has a cached suggestion.")
        return 0

    if not ollama_available():
        print(f"ERROR: Ollama is not responding on localhost:11434. Start it with "
              f"`ollama serve` (and `ollama pull {args.model}` if the model isn't "
              "pulled yet). Nothing was written.", file=sys.stderr)
        return 1

    if len(todo) > 500 and args.limit is None:
        # Measured 2026-09-17 on this machine: 0.14/s at --workers 2, 0.18/s
        # at --workers 4 (compute-bound, so concurrency past 4 workers is
        # untested and unlikely to scale linearly -- see DEFAULT_WORKERS).
        # Report against whichever benchmark is closer instead of assuming
        # a rate for worker counts never measured.
        rate = 0.18 if args.workers >= 4 else 0.14
        hours = len(todo) / rate / 3600
        print(f"Note: {len(todo):,} pairs with no --limit set -- at the "
              f"~{rate}/s measured for --workers {args.workers if args.workers in (2, 4) else 'this count (unmeasured, extrapolated)'} "
              f"that's roughly {hours:.0f} hours, not an interactive job.")

    print(f"{len(rows):,} queue rows, {len(rows) - len(todo):,} already cached, "
          f"{len(todo):,} to process. Model: {args.model}. Workers: {args.workers}.")

    start = time.time()
    processed = 0
    errors = 0
    by_decision = {"same": 0, "different": 0, "uncertain": 0}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for chunk_start in range(0, len(todo), CHECKPOINT_EVERY):
            chunk = todo[chunk_start: chunk_start + CHECKPOINT_EVERY]
            futures = {pool.submit(suggest_pair, row, model=args.model): row for row in chunk}
            new_records = []
            for future in as_completed(futures):
                row = futures[future]
                try:
                    rec = future.result()
                except Exception as e:
                    # A crash here means suggest_pair raised before building its
                    # own record (e.g. a malformed row) -- still stamp pair_id
                    # so load_checkpoint's store[rec["pair_id"]] doesn't KeyError
                    # on the very next run, undoing the resume guarantee.
                    rec = {"pair_id": pair_id(row["left_key"], row["right_key"]),
                           "left_key": row["left_key"], "right_key": row["right_key"],
                           "model": args.model, "error": f"worker crashed: {e}"[:200]}
                if "error" in rec:
                    errors += 1
                else:
                    by_decision[rec["decision"]] = by_decision.get(rec["decision"], 0) + 1
                new_records.append(rec)

            append_checkpoint(new_records, CACHE_PATH)
            processed += len(new_records)

            elapsed = time.time() - start
            done_so_far = min(chunk_start + CHECKPOINT_EVERY, len(todo))
            rate = processed / elapsed if elapsed else 0
            print(f"  {done_so_far:,}/{len(todo):,}  errors={errors} "
                  f"same={by_decision['same']} different={by_decision['different']} "
                  f"uncertain={by_decision['uncertain']}  ({rate:.2f}/s, {elapsed:.0f}s elapsed)")

    print(f"\nFinished: {processed:,} pairs processed this run ({errors:,} errors).")
    print(f"Cache now holds {len(load_checkpoint(CACHE_PATH)):,} pairs total.")
    print("Run build/build_review_tool.py to embed these into pipeline/review.html.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
