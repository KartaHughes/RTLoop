# Feedback notes (for the Devpost feedback section)

Rule of thumb: specific, reproducible, actionable. Say what you tried, what happened, and what would have helped.
Re-check every "observed" item yourself before submitting. These were seen while researching on 2026-10-22 to 2026-10-28.

## Nebius Token Factory

- **Quickstart has no Nemotron example.** The docs quickstart's sample code uses a DeepSeek model, and it does not list Nemotron model IDs. (observed)
- **Model IDs are hard to find.** The Nemotron product page shows an ID only for Super (`nvidia/nemotron-3-super-120b-a12b`). I couldn't find the Nano and Ultra IDs there and had to list them via the API. (observed; confirm after running `check_api.py`)
- **No prices on the Nemotron page.** It links out to a separate prices page. A price next to each model would help when choosing a cascade. (observed)
- **Billing docs conflict about the card.** One version of the billing page said setting up a billing account needs no bank card. The current version says a bank card is required. The Builder Program page doesn't say whether a card is needed to claim or use the $25 credit. (observed)
- **Confusing credit amounts.** $25 Builder Program credit vs a $1 trial credit (30 days) vs separate Nebius AI Cloud terms. It wasn't clear which applies to the hackathon. (observed)
- [TODO: real API experience: errors, rate limits, latency of each Nemotron size, reasoning-token behaviour, anything surprising.]
- [TODO: what worked well. Specific praise counts too.]

## NVIDIA Nemotron

- [TODO: how each model (Nano, Super, Ultra) behaved on Verilog. Failures, truncated reasoning, formatting problems.]

## NVIDIA VerilogEval

- **Needs iverilog 12 and a Unix-style build; hard on Windows.** On iverilog 11 under Windows, 5 of 156 problems fail even with the benchmark's own reference solution (unsupported cast operations, a port-name quirk, and the testbench's built-in timeout on two long-running ones). Documenting the minimum supported iverilog version and a Windows path would help. (observed: Prob082, Prob099, Prob141, Prob151, Prob156)

## Hackathon / Devpost

- [TODO: anything about onboarding, the Builder Program signup, or the rules that tripped you up.]
