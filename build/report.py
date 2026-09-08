"""Render the phase-0 join as a reviewable markdown report.

The CSV is the working artifact; this is the thing a person reads and decides
whether the project is worth continuing. Caveats are in the report itself, not
in a footnote, because the headline number is the one most likely to be quoted.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def render(data_dir: Path = None) -> Path:
    data_dir = data_dir or DATA_DIR
    summary = json.loads((data_dir / "vendor_donor_summary.json").read_text())
    with (data_dir / "vendor_donor_matches.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    strong = [r for r in rows if r["tier"] == "strong"]

    lines = [
        "# Nebraska state vendors who are also campaign contributors",
        "",
        f"Generated {date.today().isoformat()} by `build/vendor_donor_join.py`. "
        "Phase 0 of `ne-connect` — deterministic name normalization and an exact "
        "key join, no fuzzy matching, nothing merged.",
        "",
        "## What this is",
        "",
        f"- **{summary['strong_matches']} organizations** appear both as state "
        "contract vendors and as campaign contributors.",
        f"- Together they hold **${summary['strong_contract_total']:,.0f}** in state "
        "contract and purchase-order value.",
        f"- Together they gave **${summary['strong_contribution_total']:,.0f}** in "
        "reported contributions (2022–2026).",
        f"- Drawn from {summary['distinct_vendors']:,} distinct vendor names and "
        f"{summary['distinct_contributors']:,} distinct contributor names.",
        f"- {len(rows) - len(strong)} further matches are tiered **weak** and "
        "excluded from those totals.",
        "",
        "## Read this before quoting any of it",
        "",
        "- **A match is not a finding.** Two records sharing a normalized name is a "
        "reason to look, not a story. Nothing here has been verified against the "
        "Secretary of State, and no human has confirmed a single one of these pairs.",
        "- **Contract totals are award values summed across all years, not money "
        "paid.** A 2012 highway contract and a 2026 one are added together. They are "
        "not an annual figure and not a spending figure.",
        "- **3.8% of contract rows carry $0.00** — real records with no stated value, "
        "so a vendor showing $0 holds contracts, it does not lack them.",
        "- **Contributions cover 2022–2026 only** (the FirstTuesday era). Contract "
        "records reach back much further, so the two sides span different periods.",
        "- **Same name is not same company.** A national firm and an unrelated local "
        "one can share a normalized key, and subsidiaries are not resolved to parents.",
        "- **Weak-tier rows involve individuals or short keys** and collide by "
        "accident; they are listed for review, never for counting.",
        "",
        "## Strong matches",
        "",
        "| Contributions | Contract value | Entity | Recipients | Agencies |",
        "|---:|---:|---|---:|---:|",
    ]

    for row in strong[:60]:
        lines.append(
            f"| ${float(row['contribution_total']):,.0f} "
            f"| ${float(row['contract_total']):,.0f} "
            f"| {row['normalized_key'].title()} "
            f"| {row['recipients']} | {row['agencies']} |"
        )

    if len(strong) > 60:
        lines += ["", f"…and {len(strong) - 60} more in `vendor_donor_matches.csv`."]

    lines += [
        "",
        "## How a name was matched",
        "",
        "Every row in the CSV carries `normalization_applied` — the exact rules that "
        "fired to produce its key (dropped legal suffix, expanded abbreviations, "
        "removed trailing account number, and so on) — plus the raw vendor and "
        "contributor strings and a link to a sample contract record. That column is "
        "the audit trail: a match you cannot explain in one sentence is one you "
        "should not publish.",
        "",
    ]

    out = data_dir / "vendor_donor_report.md"
    out.write_text("\n".join(lines) + "\n")
    return out


if __name__ == "__main__":
    print(render())
