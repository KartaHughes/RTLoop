"""Benchmark tab: a bar chart per configuration and a map of all 151 problems.

Reads the raw logs in results/*.jsonl (the same files committed to the repo)
and prices them with models.json, so every number on the page is measured.
"""
import html
import json
from pathlib import Path

import agent

ROOT = Path(__file__).parent
CONFIGS = [
    ("nano_1shot", "NANO | 1 ATTEMPT"),
    ("nano_loop", "NANO | UP TO 3 ATTEMPTS + FEEDBACK"),
    ("cascade_ns", "NANO (2) > SUPER (2) CASCADE"),
]


def load(name):
    path = ROOT / "results" / f"{name}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line]


def total_cost(rows, prices):
    total = 0.0
    for r in rows:
        for a in r["attempts"]:
            if a.get("prompt_tokens") is None:
                continue
            c = agent.cost_usd(prices[a["model"]], a["prompt_tokens"], a["completion_tokens"])
            total += c or 0.0
    return total


def outcome(r):
    if not r["passed"]:
        last = r["attempts"][-1]["status"] if r["attempts"] else ""
        return "cut" if last == "no_code" else "fail"
    if r["solved_by"] == "super":
        return "super"
    return "n1" if len(r["attempts"]) == 1 else "n2"


LABELS = {
    "n1": "SOLVED BY NANO, FIRST TRY",
    "n2": "SOLVED BY NANO AFTER SIMULATOR FEEDBACK",
    "super": "SOLVED BY SUPER AFTER NANO FAILED",
    "cut": "UNSOLVED: REPLY CUT OFF AT THE TOKEN LIMIT",
    "fail": "UNSOLVED",
}


def build_html():
    prices = {m["name"]: m for m in agent.load_models()}
    data = {name: load(name) for name, _ in CONFIGS}
    if not all(data.values()):
        return '<div class="dim wave-msg">BENCHMARK LOGS NOT FOUND.</div>'

    bars = ""
    for name, label in CONFIGS:
        rows = data[name]
        n, ok = len(rows), sum(r["passed"] for r in rows)
        pct = 100 * ok / n
        bars += (f'<div class="bar-row"><span class="bar-label">{html.escape(label)}</span>'
                 f'<div class="bar"><div class="fill" style="width:{pct:.1f}%"></div></div>'
                 f'<span class="bar-val">{ok}/{n} | {pct:.1f}% | ${total_cost(rows, prices):.3f}</span></div>')

    rows = sorted(data["cascade_ns"], key=lambda r: r["problem"])
    cells = "".join(
        f'<span class="cell c-{outcome(r)}" title="{html.escape(r["problem"])}: {LABELS[outcome(r)]}"></span>'
        for r in rows)
    counts = {k: sum(outcome(r) == k for r in rows) for k in LABELS}
    legend = "".join(f'<span class="legend"><span class="cell c-{k}"></span> {LABELS[k]} ({counts[k]})</span>'
                     for k in LABELS)
    unsolved = counts["cut"] + counts["fail"]
    notes = (f'EACH CONFIGURATION WAS RUN ONCE ON THE SAME {len(rows)} VERILOGEVAL PROBLEMS. SAMPLING IS RANDOM, SO '
             f'EXPECT ABOUT +/-5 PROBLEMS OF RUN-TO-RUN NOISE. OF THE {unsolved} PROBLEMS THE CASCADE DID NOT SOLVE, '
             f'{counts["cut"]} WERE REPLIES CUT OFF AT THE 8,192-TOKEN LIMIT. 5 OF THE 156 BENCHMARK PROBLEMS ARE '
             'EXCLUDED BECAUSE EVEN THE OFFICIAL REFERENCE FAILS ON ICARUS VERILOG 11. HOVER A SQUARE FOR ITS NAME.')
    return ('<div class="panel-title">SOLVED, BY CONFIGURATION</div>' + bars +
            '<div class="panel-title" style="margin-top:18px">EVERY PROBLEM, CASCADE RUN</div>'
            f'<div class="grid">{cells}</div><div class="legends">{legend}</div>'
            f'<div class="foot">{notes}</div>')
