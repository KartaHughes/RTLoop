# Feedback notes (for the Devpost feedback section)

Rule of thumb: specific, reproducible, actionable. Say what you tried, what happened, and what would have helped.
Re-check every "observed" item yourself before submitting. These were seen while researching on 2026-10-22 to 2026-10-28.

## Nebius Token Factory

- **Quickstart has no Nemotron example.** The docs quickstart's sample code uses a DeepSeek model, and it does not list Nemotron model IDs. (observed)
- **Model IDs are hard to find.** The Nemotron product page shows an ID only for Super (`nvidia/nemotron-3-super-120b-a12b`). I couldn't find the Nano and Ultra IDs there and had to list them via the API. (observed; confirm after running `check_api.py`)
- **No prices on the Nemotron page.** It links out to a separate prices page. A price next to each model would help when choosing a cascade. (observed)
- **Billing docs conflict about the card.** One version of the billing page said setting up a billing account needs no bank card. The current version says a bank card is required. The Builder Program page doesn't say whether a card is needed to claim or use the $25 credit. (observed)
- **Confusing credit amounts.** $25 Builder Program credit vs a $1 trial credit (30 days) vs separate Nebius AI Cloud terms. It wasn't clear which applies to the hackathon. (observed)
- **Reasoning can use the whole output budget and return no answer.** With `max_tokens=8192`, 12 of 151 Nemotron 3 Nano replies on VerilogEval hit exactly 8,192 completion tokens and contained no final code (measured, `results/nano_1shot.jsonl`). I could not find a way to cap thinking separately from the answer. A reasoning-budget parameter, or a documented recommended `max_tokens` for reasoning-heavy tasks, would help. (measured)
- **Latency has a long tail.** For short Verilog problems Nano's per-call latency was p50 about 13s but p99 about 117s (151 calls). In the 71 Super calls in the cascade run, latency is in `results/cascade_ns.jsonl` (run `python agent.py report --name cascade_ns` for the overall p50/p99). Documenting expected latency per model would help people choose cascade thresholds. (measured; the Super-specific numbers still need pulling from the log before submitting)
- **Transient connection errors.** 2 of 151 first-run calls failed with a plain "Connection error" and succeeded on retry. A documented retry policy or rate-limit guidance for the OpenAI-compatible endpoint would help. (measured)
- **Model naming is inconsistent.** The model list returns IDs such as `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `nvidia/nemotron-3-super-120b-a12b`, `nvidia/Nemotron-3-Ultra-550b-a55b`, `nvidia/Nemotron-3.5-Super-VL` and `nvidia/Nemotron-3_5-Lightning`, with mixed casing and separators. It is easy to mistype one, and it wasn't clear which are text-only (VL, Lightning). A short per-model description in the API's model list would help. (observed)
- **The prices page needs a login, and Ultra wasn't listed.** I priced Nano and Super from the console, but found no Ultra row, so I couldn't estimate a cascade that includes Ultra and left it out. Public prices for every model would let builders plan a budget before signing up. (observed)
- **Builder Program credit arrived late in the build.** The hackathon page tells entrants to join the Builder Program for credits, but my application was "under review for up to two business days" and I worked from the $1 trial credit for most of the build. Approval came about a day after the review email [TODO: confirm the exact date and time you applied and were approved], which is faster than the stated window, but with a deadline about two weeks out, instant credits for registered hackathon participants would remove the blocker. (observed)
- **What worked well:** [TODO: your own genuine praise, e.g. the OpenAI-compatible endpoint worked with the standard `openai` Python client unchanged, and the cost per problem was tiny: a full 151-problem baseline cost $0.084.]
- [TODO: anything else you hit yourself.]
- [TODO: what worked well. Specific praise counts too.]

## NVIDIA Nemotron

- [TODO: how each model (Nano, Super, Ultra) behaved on Verilog. Failures, truncated reasoning, formatting problems.]

## NVIDIA VerilogEval

- **Needs iverilog 12 and a Unix-style build; hard on Windows.** On iverilog 11 under Windows, 5 of 156 problems fail even with the benchmark's own reference solution (unsupported cast operations, a port-name quirk, and the testbench's built-in timeout on two long-running ones). Documenting the minimum supported iverilog version and a Windows path would help. (observed: Prob082, Prob099, Prob141, Prob151, Prob156)

## Hackathon / Devpost

- [TODO: anything about onboarding, the Builder Program signup, or the rules that tripped you up.]
