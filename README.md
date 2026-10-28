# RTLoop

An agent that writes Verilog, simulates it, and fixes its own bugs. Built for the Nebius x NVIDIA Global AI Hackathon (Coding and Agentic Engineering track).

RTLoop asks an NVIDIA Nemotron model (served on Nebius Token Factory) to implement a hardware spec, runs the result in the Icarus Verilog simulator against a testbench, and feeds any compile errors or mismatches back to the model for another attempt. If a small model keeps failing, it escalates to a larger one (Nemotron 3 Nano, then Super, then Ultra). Every model call logs tokens, latency and cost.

## Results

[TODO: fill from `python agent.py report --name <run>`. Only measured numbers. State the problem count, the subset and seed, and the number of runs per configuration.]

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
