# RTLoop

An agent that writes Verilog, simulates it, and fixes its own bugs. Built for the Nebius x NVIDIA Global AI Hackathon (Coding and Agentic Engineering track).

RTLoop asks an NVIDIA Nemotron model (served on Nebius Token Factory) to implement a hardware spec, runs the result in the Icarus Verilog simulator against a testbench, and feeds any compile errors or mismatches back to the model for another attempt. If a small model keeps failing, it escalates to a larger one (Nemotron 3 Nano, then Super, then Ultra). Every model call logs tokens, latency and cost.

**Live demo:** https://rtloop.onrender.com (free tier: it sleeps when idle, so the first load can take about a minute).

## Results

Measured on 151 VerilogEval spec-to-RTL problems (see Benchmark below), with a cap of 8,192 output tokens per model call. Costs are computed from token counts and Nebius Token Factory list prices (Nano $0.06 in / $0.24 out per 1M tokens, Super $0.30 / $0.90).

| Configuration | Solved | Cost |
|---|---|---|
| Nemotron 3 Nano, one attempt | 92 / 151 (60.9%) | $0.084 |
| Nano, up to 3 attempts with simulator feedback | 114 / 151 (75.5%) | $0.210 |
| Nano (2 attempts), then Super (2 attempts) | 126 / 151 (83.4%) | $0.382 |

- Super was only called on the problems Nano could not solve, and it solved 16 of them.
- **Each configuration was run once.** Sampling is random: in the retry-loop run only 85 problems passed on the first attempt, against 92 in the one-shot run under identical conditions. Treat differences of a few problems as noise. [TODO: add repeat-run ranges here once measured.]
- The attempt budgets are not identical across rows (3 calls for Nano retries, up to 4 calls for the cascade).
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

Every generation is a runtime call to Nebius Token Factory's OpenAI-compatible API using NVIDIA Nemotron 3 models. [TODO: what Token Factory made easy or hard.]

## Limitations

- Runs on Icarus Verilog 11; five benchmark problems are excluded as described above.
- Generated code is executed in a simulator. Treat model output as untrusted code.
- [TODO: anything else you actually found.]

## Licence

MIT. See `LICENSE`.
