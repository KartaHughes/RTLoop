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
    ("NANO | 1 ATTEMPT", ["nano_1shot", "nano_1shot_r2", "nano_1shot_r3"]),
    ("NANO | UP TO 3 ATTEMPTS + FEEDBACK", ["nano_loop", "nano_loop_r2", "nano_loop_r3"]),
    ("NANO (2) > SUPER (2) CASCADE", ["cascade_ns", "cascade_ns_r2", "cascade_ns_r3"]),
    ("NANO > SUPER > ULTRA (2 EACH), 1 RUN", ["cascade_nsu"]),
]
GRID_RUN = "cascade_nsu"  # the problem map shows the Nano > Super > Ultra run


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
    if r["solved_by"] in ("super", "ultra"):
        return r["solved_by"]
    return "n1" if len(r["attempts"]) == 1 else "n2"


LABELS = {
    "n1": "SOLVED BY NANO, FIRST TRY",
    "n2": "SOLVED BY NANO AFTER SIMULATOR FEEDBACK",
    "super": "SOLVED BY SUPER AFTER NANO FAILED",
    "ultra": "SOLVED BY ULTRA AFTER NANO AND SUPER FAILED",
    "cut": "UNSOLVED: REPLY CUT OFF AT THE TOKEN LIMIT",
    "fail": "UNSOLVED",
}


def build_html():
    prices = {m["name"]: m for m in agent.load_models()}
    data = {name: load(name) for _, runs in CONFIGS for name in runs}
    if not all(data.values()):
        return '<div class="dim wave-msg">BENCHMARK LOGS NOT FOUND.</div>'

    bars = ""
    for label, runs in CONFIGS:
        counts = [sum(r["passed"] for r in data[n]) for n in runs]
        costs = [total_cost(data[n], prices) for n in runs]
        total = len(data[runs[0]])
        mean = sum(counts) / len(counts)
        pct, lo, hi = 100 * mean / total, 100 * min(counts) / total, 100 * max(counts) / total
        unpriced = any(prices[a["model"]]["in_per_m"] is None for n in runs for r in data[n]
                       for a in r["attempts"] if a.get("prompt_tokens") is not None)
        if len(runs) > 1:
            value = (f'{mean:.1f}/{total} MEAN | RANGE {min(counts)}-{max(counts)} | '
                     f'{pct:.1f}% | ${sum(costs) / len(costs):.3f}/RUN')
        else:
            value = f'{counts[0]}/{total} | 1 RUN | {pct:.1f}% | ${costs[0]:.3f}' + (' EXCL. ULTRA' if unpriced else '')
        bars += (f'<div class="bar-row"><span class="bar-label">{html.escape(label)}</span>'
                 f'<div class="bar"><div class="fill" style="width:{pct:.1f}%"></div>'
                 f'<div class="range" style="left:{lo:.1f}%;width:{max(hi - lo, 0.6):.1f}%"></div></div>'
                 f'<span class="bar-val">{value}</span></div>')

    rows = sorted(data[GRID_RUN], key=lambda r: r["problem"])
    cells = "".join(
        f'<span class="cell c-{outcome(r)}" title="{html.escape(r["problem"])}: {LABELS[outcome(r)]}"></span>'
        for r in rows)
    counts = {k: sum(outcome(r) == k for r in rows) for k in LABELS}
    legend = "".join(f'<span class="legend"><span class="cell c-{k}"></span> {LABELS[k]} ({counts[k]})</span>'
                     for k in LABELS)
    unsolved = counts["cut"] + counts["fail"]
    notes = (f'EACH CONFIGURATION WAS RUN THREE TIMES ON THE SAME {len(rows)} VERILOGEVAL PROBLEMS. THE BAR SHOWS THE MEAN '
             f'AND THE PALE MARKER SHOWS THE RANGE ACROSS THE THREE RUNS, BECAUSE SAMPLING IS RANDOM. THE FOURTH BAR IS A SINGLE RUN '
             f'(ULTRA HAS NO PUBLISHED PRICE, SO ITS COST IS NOT SHOWN). THE MAP SHOWS THAT NANO > SUPER > ULTRA RUN. OF THE {unsolved} PROBLEMS IT DID NOT SOLVE, '
             f'{counts["cut"]} WERE REPLIES CUT OFF AT THE 8,192-TOKEN LIMIT. 5 OF THE 156 BENCHMARK PROBLEMS ARE '
             'EXCLUDED BECAUSE EVEN THE OFFICIAL REFERENCE FAILS ON ICARUS VERILOG 11. HOVER A SQUARE FOR ITS NAME.')
    return ('<div class="panel-title">SOLVED, BY CONFIGURATION</div>' + bars +
            '<div class="panel-title" style="margin-top:18px">EVERY PROBLEM, CASCADE RUN</div>'
            f'<div class="grid">{cells}</div><div class="legends">{legend}</div>'
            f'<div class="foot">{notes}</div>')
