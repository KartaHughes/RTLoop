"""Compile and simulate a candidate Verilog module against a VerilogEval problem.

VerilogEval ships three files per problem: a prompt, a reference module
(RefModule) and a testbench that instantiates both the reference and the
candidate (TopModule) and prints "Mismatches: N in M samples".

Usage:
    python -I runner.py selfcheck [--limit N]
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DATASET = Path(__file__).parent / "third_party" / "verilog-eval" / "dataset_spec-to-rtl"
CUSTOM = Path(__file__).parent / "custom_problems"  # our own problems, same file format
TIMEOUT_S = 30
MAX_FEEDBACK_CHARS = 2000

IVERILOG_FLAGS = ["-Wall", "-Winfloop", "-Wno-timescale", "-g2012", "-s", "tb"]
MISMATCH_RE = re.compile(r"Mismatches:\s*(\d+)\s+in\s+(\d+)\s+samples")


# Even the benchmark's own reference solution fails these on Icarus Verilog 11
# (unsupported cast operations, a port-name quirk, or the testbench's built-in
# timeout). Excluded so every reported number is over problems we can verify.
EXCLUDED = {
    "Prob082_lfsr32",
    "Prob099_m2014_q6c",
    "Prob141_count_clock",
    "Prob151_review2015_fsm",
    "Prob156_review2015_fancytimer",
}


def list_problems():
    """Problem ids, e.g. 'Prob001_zero' (151 of the 156, see EXCLUDED)."""
    return sorted(
        p.name[: -len("_prompt.txt")]
        for p in DATASET.glob("*_prompt.txt")
        if p.name[: -len("_prompt.txt")] not in EXCLUDED
    )


def list_custom_problems():
    """Hand-written problems in custom_problems/ (kept out of the benchmark numbers)."""
    return sorted(p.name[: -len("_prompt.txt")] for p in CUSTOM.glob("*_prompt.txt"))


def _problem_dir(problem_id):
    return CUSTOM if (CUSTOM / f"{problem_id}_prompt.txt").exists() else DATASET


def get_prompt(problem_id):
    return (_problem_dir(problem_id) / f"{problem_id}_prompt.txt").read_text(encoding="utf-8", errors="replace")


def get_reference(problem_id):
    return (_problem_dir(problem_id) / f"{problem_id}_ref.sv").read_text(encoding="utf-8", errors="replace")


def run_candidate(problem_id, code, timeout=TIMEOUT_S, want_wave=False):
    """Simulate `code` (must define TopModule) against the problem's testbench.

    Returns a dict with:
      status:   "pass" | "compile_error" | "mismatch" | "timeout" | "no_result"
      mismatches, samples: ints (or None)
      feedback: text to show the model on a retry (empty on pass)
    """
    iverilog = shutil.which("iverilog")
    vvp = shutil.which("vvp")
    if not iverilog or not vvp:
        raise RuntimeError("iverilog/vvp not found on PATH")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "sample.sv").write_text(code, encoding="utf-8")
        problem_dir = _problem_dir(problem_id)
        shutil.copy(problem_dir / f"{problem_id}_ref.sv", tmp / "ref.sv")
        shutil.copy(problem_dir / f"{problem_id}_test.sv", tmp / "test.sv")

        try:
            comp = subprocess.run(
                [iverilog, *IVERILOG_FLAGS, "-o", "sim.vvp", "sample.sv", "ref.sv", "test.sv"],
                cwd=tmp, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _result("timeout", feedback="Compilation timed out.")
        if comp.returncode != 0:
            return _result("compile_error", feedback=_clip(comp.stderr or comp.stdout))

        try:
            sim = subprocess.run(
                [vvp, "sim.vvp"], cwd=tmp, capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return _result("timeout", feedback="Simulation timed out (possible infinite loop).")

        vcd = ""
        vcd_path = tmp / "wave.vcd"
        if want_wave and vcd_path.exists() and vcd_path.stat().st_size < 8_000_000:
            vcd = vcd_path.read_text(errors="replace")

    out = sim.stdout
    match = MISMATCH_RE.search(out)
    if "TIMEOUT" in out or not match:
        return _result("no_result", feedback=_clip(out or sim.stderr), vcd=vcd)
    mismatches, samples = int(match.group(1)), int(match.group(2))
    if mismatches == 0 and samples > 0:
        return _result("pass", mismatches, samples, vcd=vcd)
    hints = "\n".join(line for line in out.splitlines() if line.startswith("Hint:"))
    return _result("mismatch", mismatches, samples, feedback=_clip(hints or out), vcd=vcd)


def _result(status, mismatches=None, samples=None, feedback="", vcd=""):
    return {"status": status, "mismatches": mismatches, "samples": samples,
            "feedback": feedback, "vcd": vcd}


def _clip(text):
    return text.strip()[:MAX_FEEDBACK_CHARS]


# --- Self-check: known-good must pass, known-bad must fail -------------------

MUTATIONS = [("&", "|"), ("|", "&"), ("==", "!="), ("+", "-"), ("1'b0", "1'b1"), ("1'b1", "1'b0")]


def _as_top(ref_code):
    return ref_code.replace("RefModule", "TopModule")


def _mutate(code):
    """Return the first textual mutation of `code` that changes it, else None."""
    for old, new in MUTATIONS:
        if old in code:
            return code.replace(old, new, 1)
    return None


def selfcheck(limit=None):
    problems = list_problems()[:limit]
    good_fail, empty_pass, mutants, mutants_caught = [], [], 0, 0
    for pid in problems:
        ref = _as_top(get_reference(pid))
        if run_candidate(pid, ref)["status"] != "pass":
            good_fail.append(pid)
        if run_candidate(pid, "module TopModule(); endmodule")["status"] == "pass":
            empty_pass.append(pid)
        mutated = _mutate(ref)
        if mutated and mutated != ref:
            mutants += 1
            if run_candidate(pid, mutated)["status"] != "pass":
                mutants_caught += 1
    print(f"Problems checked:            {len(problems)}")
    print(f"Known-good (ref) failing:    {len(good_fail)}  {good_fail[:10]}")
    print(f"Empty module wrongly passing:{len(empty_pass)}  {empty_pass[:10]}")
    print(f"Mutants caught:              {mutants_caught}/{mutants} (survivors may be equivalent mutants)")
    return not good_fail and not empty_pass


def selfcheck_custom():
    """Each custom problem: its reference must pass, every <id>_bad*.sv must fail."""
    ok = True
    for pid in list_custom_problems():
        good = run_candidate(pid, _as_top(get_reference(pid)))["status"]
        print(f"{pid}: reference -> {good}")
        ok = ok and good == "pass"
        for bad in sorted(CUSTOM.glob(f"{pid}_bad*.sv")):
            status = run_candidate(pid, bad.read_text())["status"]
            print(f"  {bad.name}: {status}")
            ok = ok and status != "pass"
    return ok


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "selfcheck" and "--custom" in sys.argv:
        sys.exit(0 if selfcheck_custom() else 1)
    if len(sys.argv) >= 2 and sys.argv[1] == "selfcheck":
        lim = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
        sys.exit(0 if selfcheck(lim) else 1)
    print(__doc__)
