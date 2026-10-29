"""RTLoop agent: ask a Nemotron model for Verilog, simulate it, feed failures
back, and escalate to a larger model when a smaller one keeps failing.

Usage:
    python agent.py run --name nano_1shot --models 0 --attempts 1 --limit 30
    python agent.py run --name nano_loop  --models 0 --attempts 3 --limit 30
    python agent.py run --name cascade    --models 0,1,2 --attempts 2 --limit 30
    python agent.py report --name cascade

--models are indexes into models.json (cheapest first). Re-running with the same
--name resumes, skipping problems already in runs/<name>/results.jsonl.
"""
import argparse
import json
import os
import random
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from openai import OpenAI

import runner
from check_api import BASE_URL, load_env

ROOT = Path(__file__).parent
MAX_TOKENS = int(os.environ.get("RTLOOP_MAX_TOKENS", "8192"))

SYSTEM = (
    "You are an expert digital hardware engineer who writes correct, simulatable "
    "SystemVerilog. Reply with ONE complete module named TopModule inside a single "
    "```systemverilog code block. Do not include testbenches or any other code blocks."
)
FEEDBACK = (
    "Your module did not pass verification.\nResult: {status}\nDetails:\n{details}\n\n"
    "Fix the problem and reply with the complete corrected TopModule in a single "
    "```systemverilog code block."
)

THINK_RE = re.compile(r"<think>.*?</think>", re.S)
FENCE_RE = re.compile(r"```(?:systemverilog|verilog|sv)?[ \t]*\n(.*?)```", re.S | re.I)


def extract_code(text):
    """Last fenced block containing a module; falls back to raw text."""
    text = THINK_RE.sub("", text or "")
    for block in reversed(FENCE_RE.findall(text)):
        if "module" in block:
            return block.strip()
    return text.strip() if "module" in text else ""


def load_models():
    return json.loads((ROOT / "models.json").read_text())


def cost_usd(cfg, prompt_tokens, completion_tokens):
    if cfg.get("in_per_m") is None or cfg.get("out_per_m") is None:
        return None
    return (prompt_tokens * cfg["in_per_m"] + completion_tokens * cfg["out_per_m"]) / 1e6


class Budget:
    """Thread-safe spend cap so a bug can't burn through credits."""

    def __init__(self, max_tokens, max_usd):
        self.max_tokens, self.max_usd = max_tokens, max_usd
        self.tokens, self.usd = 0, 0.0
        self.lock = threading.Lock()

    def add(self, tokens, usd):
        with self.lock:
            self.tokens += tokens
            self.usd += usd or 0.0

    def exhausted(self):
        with self.lock:
            return self.tokens >= self.max_tokens or (self.max_usd and self.usd >= self.max_usd)


def call_model(client, model_id, messages):
    for delay in (2, 8, None):  # retry transient API errors with backoff
        try:
            return client.chat.completions.create(
                model=model_id, messages=messages, max_tokens=MAX_TOKENS
            )
        except Exception:
            if delay is None:
                raise
            time.sleep(delay)


def solve(client, models, problem_id, attempts_per_model, budget):
    """Run the retry loop (and cascade, if several models) on one problem."""
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": runner.get_prompt(problem_id)},
    ]
    log = []
    for cfg in models:
        for attempt in range(1, attempts_per_model + 1):
            if budget.exhausted():
                return {"problem": problem_id, "passed": False, "stopped": "budget", "attempts": log}
            start = time.time()
            try:
                resp = call_model(client, cfg["id"], messages)
            except Exception as exc:
                log.append({"model": cfg["name"], "attempt": attempt, "status": "api_error",
                            "error": str(exc)[:200]})
                continue
            latency = time.time() - start
            text = resp.choices[0].message.content or ""
            pt, ct = resp.usage.prompt_tokens, resp.usage.completion_tokens
            usd = cost_usd(cfg, pt, ct)
            budget.add(pt + ct, usd)

            code = extract_code(text)
            if code:
                result = runner.run_candidate(problem_id, code)
            else:
                result = {"status": "no_code", "feedback": "No SystemVerilog code block was found in your reply."}
            log.append({"model": cfg["name"], "attempt": attempt, "status": result["status"],
                        "prompt_tokens": pt, "completion_tokens": ct,
                        "latency_s": round(latency, 2), "cost_usd": usd})
            if result["status"] == "pass":
                return {"problem": problem_id, "passed": True, "solved_by": cfg["name"], "attempts": log}
            messages += [
                {"role": "assistant", "content": text or "(empty reply)"},
                {"role": "user", "content": FEEDBACK.format(status=result["status"],
                                                            details=result["feedback"] or "(none)")},
            ]
    return {"problem": problem_id, "passed": False, "attempts": log}


def cmd_run(args):
    load_env(ROOT / ".env")
    if not os.environ.get("NEBIUS_API_KEY"):
        sys.exit("NEBIUS_API_KEY not set (see .env.example)")
    all_models = load_models()
    models = [all_models[int(i)] for i in args.models.split(",")]
    for cfg in models:
        if cfg["id"] == "TODO":
            sys.exit(f"Set the model id for '{cfg['name']}' in models.json (run check_api.py to list them)")

    problems = runner.list_custom_problems() if args.custom else runner.list_problems()
    if args.only_failed_from:  # re-try only the problems a previous run did not solve
        prev = ROOT / "runs" / args.only_failed_from / "results.jsonl"
        failed = {json.loads(line)["problem"] for line in prev.read_text(encoding="utf-8-sig").splitlines()
                  if line and not json.loads(line)["passed"]}
        problems = [p for p in problems if p in failed]
    if args.limit and not args.custom:
        problems = sorted(random.Random(0).sample(problems, args.limit))  # fixed seed: same subset every run

    out_dir = ROOT / "runs" / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"
    done = set()
    if results_path.exists():
        done = {json.loads(line)["problem"] for line in results_path.read_text(encoding="utf-8-sig").splitlines() if line}
    todo = [p for p in problems if p not in done]
    print(f"{args.name}: {len(todo)} to run ({len(done)} already done), models={[m['name'] for m in models]}, "
          f"attempts/model={args.attempts}")

    client = OpenAI(base_url=BASE_URL, api_key=os.environ["NEBIUS_API_KEY"])
    budget = Budget(args.max_tokens, args.max_usd)
    write_lock = threading.Lock()
    counter = {"n": 0}

    def work(pid):
        try:
            res = solve(client, models, pid, args.attempts, budget)
        except Exception as exc:  # don't let one bad problem kill the run; it is retried on resume
            print(f"ERROR on {pid}: {exc!r}", flush=True)
            return
        with write_lock:
            with results_path.open("a") as f:
                f.write(json.dumps(res) + "\n")
            counter["n"] += 1
            print(f"[{counter['n']}/{len(todo)}] {pid}: {'PASS' if res['passed'] else 'fail'} "
                  f"(tokens so far {budget.tokens})", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, todo))
    print(f"Done. Tokens used: {budget.tokens}")
    cmd_report(args)


def pct(sorted_vals, p):
    return sorted_vals[min(len(sorted_vals) - 1, int(p / 100 * len(sorted_vals)))] if sorted_vals else None


def cmd_report(args):
    path = ROOT / "runs" / args.name / "results.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line]
    n = len(rows)
    passed = sum(r["passed"] for r in rows)
    calls = [a for r in rows for a in r["attempts"] if a.get("latency_s") is not None]
    lat = sorted(a["latency_s"] for a in calls)
    tokens = sum(a["prompt_tokens"] + a["completion_tokens"] for a in calls)
    # Price from token counts and the current models.json, so older runs get priced too.
    by_name = {m["name"]: m for m in load_models()}
    costs = [cost_usd(by_name[a["model"]], a["prompt_tokens"], a["completion_tokens"]) for a in calls]
    solved_by = {}
    for r in rows:
        if r["passed"]:
            solved_by[r["solved_by"]] = solved_by.get(r["solved_by"], 0) + 1
    print(f"\n== {args.name} ==")
    print(f"Problems: {n}   Passed: {passed} ({100 * passed / n:.1f}%)" if n else "No results")
    if not n:
        return
    print(f"Model calls: {len(calls)} (avg {len(calls) / n:.2f} per problem)   Tokens: {tokens}")
    print(f"Solved by model: {solved_by}")
    print(f"Latency per call: p50 {pct(lat, 50)}s  p99 {pct(lat, 99)}s")
    print("Cost: " + (f"${sum(costs):.3f} total, ${sum(costs) / n:.4f} per problem"
                      if costs and None not in costs else "unknown (set prices in models.json)"))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run")
    run.add_argument("--name", required=True)
    run.add_argument("--models", default="0")
    run.add_argument("--attempts", type=int, default=1)
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--custom", action="store_true", help="run the hand-written problems in custom_problems/")
    run.add_argument("--only-failed-from", dest="only_failed_from", default="",
                     help="only run problems that this earlier run (name under runs/) failed")
    run.add_argument("--workers", type=int, default=6)
    run.add_argument("--max-tokens", type=int, default=3_000_000, dest="max_tokens")
    run.add_argument("--max-usd", type=float, default=0.0, dest="max_usd")
    run.set_defaults(func=cmd_run)
    rep = sub.add_parser("report")
    rep.add_argument("--name", required=True)
    rep.set_defaults(func=cmd_report)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
