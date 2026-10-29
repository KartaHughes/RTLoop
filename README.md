# RTLoop

An agent that writes Verilog, simulates it, and fixes its own bugs. Built for the Nebius x NVIDIA Global AI Hackathon (Coding and Agentic Engineering track).

RTLoop asks an NVIDIA Nemotron model (served on Nebius Token Factory) to implement a hardware spec, runs the result in the Icarus Verilog simulator against a testbench, and feeds any compile errors or mismatches back to the model for another attempt. If a small model keeps failing, it escalates to a larger one (Nemotron 3 Nano, then Super, then Ultra). Every model call logs tokens, latency and cost.

**Live demo:** https://rtloop.onrender.com (free tier: it sleeps when idle, so the first load can take about a minute).

## Results

Measured on 151 VerilogEval spec-to-RTL problems (see Benchmark below), with a cap of 8,192 output tokens per model call. Costs are computed from token counts and Nebius Token Factory list prices (Nano $0.06 in / $0.24 out per 1M tokens, Super $0.30 / $0.90).

Each configuration was run **three times** (sampling is random). Solved counts per run, mean, and cost per run:

| Configuration | Solved per run | Mean | Range | Cost per run |
|---|---|---|---|---|
| Nemotron 3 Nano, one attempt | 92, 88, 90 | 90.0 / 151 (59.6%) | 88-92 | $0.084-$0.090 |
| Nano, up to 3 attempts with simulator feedback | 114, 117, 115 | 115.3 / 151 (76.4%) | 114-117 | $0.197-$0.211 |
| Nano (2 attempts), then Super (2 attempts) | 126, 125, 123 | 124.7 / 151 (82.6%) | 123-126 | $0.382-$0.443 |
| Nano, then Super, then Ultra (2 attempts each), **one run only** | 133 | 133 / 151 (88.1%) | n/a | $0.430 for Nano and Super; Ultra not priced |

- The gaps between configurations (about 90, then 115, then 125 solved) are much larger than the run-to-run spread within each (2 to 4 problems).
- Super was only called on problems Nano could not solve; in the first cascade run it solved 16 of them.
- The attempt budgets are not identical across rows (3 calls for Nano retries, up to 4 calls for the cascade).
- **The Nano, Super, Ultra row is a single run**, so it has no range; it solved 18 more problems than the three-run Nano retry mean and 8 more than the cascade mean, but treat that gap as indicative. In that run, Nano solved 109, Super 17 and Ultra 7 (Ultra was handed 25 problems). Of the 18 unsolved, 13 were mismatches, 4 were compile errors and 1 was cut off at the token limit.
- Nebius lists no Ultra price in the console I could see, so no Ultra cost is reported. In that run Ultra made 47 calls (168,069 prompt tokens and 241,342 completion tokens, in `results/cascade_nsu.jsonl`).
- Ultra was also tried on its own, from a fresh start, on the 25 problems the first Nano, Super run left unsolved (`ultra_unsolved`, 2 attempts each): it solved 14. In the cascade it solved 7 of the 25 problems it was handed, but those are a different set of problems, and in the cascade Ultra sees the earlier failed attempts in its context. I did not test whether that history helps or hurts, so I make no claim about it.
- 7 of the 25 problems unsolved by the cascade were replies cut off at the 8,192-token cap, so the cap understates what the models can do.
- `Trade001_top_of_book` is one hand-written problem, so it is a demonstration, not a statistic. In the single run recorded in `results/trade.jsonl`, Nano failed twice and Super solved it.
- Raw per-problem logs for every run (attempts, tokens, latency, status) are in `results/*.jsonl`. Reproduce a summary with `python agent.py report --name <run>` after copying a log to `runs/<run>/results.jsonl`.

## How it works

- `runner.py`: compiles and simulates a candidate module against a problem's reference and testbench; returns pass / compile_error / mismatch / timeout plus feedback for the model. `python -I runner.py selfcheck` verifies the harness: reference solutions must pass, deliberately broken modules must fail.
- `agent.py`: the retry loop, the model cascade, the spend cap, and per-call logging and reporting.
- `custom_problems/`: hand-written problems in the same format as the benchmark. `Trade001_top_of_book` is a top-of-book quote tracker (latest bid and ask, a crossed-book flag, and the spread) with six deliberately buggy variants used to prove the testbench catches real mistakes.

## Benchmark

Evaluated on [VerilogEval](https://github.com/NVlabs/verilog-eval) (NVIDIA Research, MIT licence), spec-to-RTL problems. Five of the 156 problems are excluded because even the benchmark's own reference solution fails on Icarus Verilog 11 (unsupported cast operations, a port-name quirk, and the testbench's built-in timeout), so results are over **151 problems**: `Prob082_lfsr32`, `Prob099_m2014_q6c`, `Prob141_count_clock`, `Prob151_review2015_fsm`, `Prob156_review2015_fancytimer`.

## Setup

Requirements: Python 3.10+, [Icarus Verilog](https://steveicarus.github.io/iverilog/) on your `PATH` (developed on 11.0), git, and a Nebius Token Factory API key.

```bash
git clone https://github.com/KartaHughes/RTLoop.git
cd RTLoop
git clone --depth 1 https://github.com/NVlabs/verilog-eval.git third_party/verilog-eval
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # on Linux/macOS: .venv/bin/pip
cp .env.example .env                            # then put your key in .env
```

Set the model IDs and prices in `models.json`, then:

```bash
python check_api.py                                                   # list Nemotron models, test one call
python runner.py selfcheck                                            # verify the harness
python agent.py run --name nano_1shot --models 0 --attempts 1 --limit 30
python agent.py run --name nano_loop  --models 0 --attempts 3 --limit 30
python agent.py run --name cascade    --models 0,1,2 --attempts 2 --limit 30
python agent.py report --name cascade
python agent.py run --name trade --models 0,1,2 --attempts 2 --custom # the trading problem
```

## How Nebius Token Factory and NVIDIA Nemotron are used

Every generation is a runtime call to Nebius Token Factory's OpenAI-compatible API using NVIDIA Nemotron 3 models: Nano (`nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`), Super (`nvidia/nemotron-3-super-120b-a12b`) and Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`). The cascade is built around the three sizes: Nano makes the first attempts, Super takes over when Nano keeps failing, and Ultra is the last resort.

Where Token Factory accelerated the work:
- The standard `openai` Python client worked with only the base URL changed, so the agent needed no provider-specific code.
- Per-token pricing made large experiments cheap: a full 151-problem Nano run costs about $0.09 and takes minutes, which is what made three repeats of every configuration affordable.
- Having three model sizes behind one API made the escalation design (and its measurement) straightforward.

Frictions I hit (reasoning replies that used the whole 8,192-token budget, unlisted Ultra pricing, a long latency tail) are reported in the Results notes above and in my hackathon feedback.

## Limitations

- Runs on Icarus Verilog 11; five benchmark problems are excluded as described above.
- Generated code is executed in a simulator. Treat model output as untrusted code.
- Results are from one benchmark (VerilogEval, spec-to-RTL) with an 8,192-token output cap per call; a higher cap would likely recover some of the replies that were cut off.
- The three-stage (Nano, Super, Ultra) result is a single run, and Ultra has no price here, so its cost is not reported.
- The hosted demo is on a free tier: it sleeps when idle (first load can take about a minute) and is limited to preset problems, a per-visitor rate limit and a daily spend cap.
- The market view and some waveform windows show only the early part of a test; mismatches later in a test appear only in the waveform panel.

## Licence

MIT. See `LICENSE`.
