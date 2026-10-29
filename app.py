"""RTLoop demo: watch an agent write Verilog, simulate it, and fix its own bugs.

The API key is read from the server's environment (NEBIUS_API_KEY) and never
reaches the browser. Visitors can only pick from preset problems, and runs are
rate-limited with a daily spend cap so a public demo can't drain the account.
"""
import html
import os
import subprocess
import threading
import time
from pathlib import Path

import gradio as gr
from openai import OpenAI

import agent
import bench_view
import market
import runner
import wave
from check_api import BASE_URL, load_env

ROOT = Path(__file__).parent
load_env(ROOT / ".env")

# Benchmark problems come from NVIDIA's VerilogEval; fetch on first start if absent.
if not runner.DATASET.exists():
    subprocess.run(
        ["git", "clone", "--depth", "1", "https://github.com/NVlabs/verilog-eval.git",
         str(ROOT / "third_party" / "verilog-eval")],
        check=True,
    )

MODELS = agent.load_models()
CLIENT = OpenAI(base_url=BASE_URL, api_key=os.environ.get("NEBIUS_API_KEY", "missing"))

PRESET_IDS = [
    "Trade001_top_of_book",
    "Prob119_fsm3", "Prob075_counter_2bc", "Prob097_mux9to1v", "Prob085_shift4",
    "Prob047_dff8ar", "Prob030_popcount255", "Prob143_fsm_onehot", "Prob112_always_case2",
    "Prob005_notgate", "Prob007_wire", "Prob011_norgate",
]


def label_for(pid):
    if pid.startswith("Trade"):
        return "TRADE001 | TOP-OF-BOOK QUOTE TRACKER (CUSTOM)"
    return f"{pid[:7].upper()} | {pid[8:].replace('_', ' ').upper()}"


PRESETS = {label_for(p): p for p in PRESET_IDS}
LABELS = list(PRESETS)
MODE_NANO = "NANO ONLY"
MODE_CASCADE = "NANO > SUPER CASCADE"
MODE_ULTRA = "NANO > SUPER > ULTRA"
# Cap-only estimate for models without a listed price (Ultra): deliberately high, so the
# daily spend cap can never be bypassed. It is never shown as a real cost.
UNPRICED_CAP_USD_PER_M = 3.0


class Guard:
    """Per-visitor hourly limit plus a daily spend cap for the whole demo."""

    def __init__(self):
        self.per_ip = int(os.environ.get("RTLOOP_IP_LIMIT", "6"))
        self.daily_usd = float(os.environ.get("RTLOOP_DAILY_USD", "2.0"))
        self.lock = threading.Lock()
        self.hits, self.day, self.spent = {}, time.strftime("%Y-%m-%d"), 0.0

    def check(self, ip):
        with self.lock:
            today = time.strftime("%Y-%m-%d")
            if today != self.day:
                self.day, self.spent = today, 0.0
            if self.spent >= self.daily_usd:
                return False, "DAILY SPEND CAP REACHED. TRY AGAIN TOMORROW."
            recent = [t for t in self.hits.get(ip, []) if time.time() - t < 3600]
            if len(recent) >= self.per_ip:
                return False, f"RATE LIMIT: {self.per_ip} RUNS PER HOUR."
            self.hits[ip] = recent + [time.time()]
            return True, ""

    def add_cost(self, usd):
        with self.lock:
            self.spent += usd


GUARD = Guard()


def client_ip(request):
    fwd = request.headers.get("x-forwarded-for", "") if request else ""
    return fwd.split(",")[0].strip() or (request.client.host if request else "local")


def esc(text):
    return html.escape(str(text))


def banner(state, text, kind):
    return f'<div class="banner {kind}"><span class="state">{esc(state)}</span> {esc(text)}</div>'


def render_log(rows, pending=None, spent=0.0):
    body = ""
    for i, r in enumerate(rows, 1):
        cls = "ok" if r["status"] == "pass" else "bad"
        cost = f"${r['cost']:.4f}" if r["cost"] is not None else "n/a"
        body += (f'<tr><td>{i}</td><td>{esc(r["model"].upper())}</td>'
                 f'<td class="{cls}">{esc(r["status"].upper())}</td>'
                 f'<td>{r["tokens"]}</td><td>{r["secs"]:.1f}s</td><td>{cost}</td></tr>')
    if pending:
        body += (f'<tr class="pend"><td>{len(rows) + 1}</td><td>{esc(pending.upper())}</td>'
                 '<td class="run">RUNNING...</td><td>-</td><td>-</td><td>-</td></tr>')
    if not body:
        body = '<tr><td colspan="6" class="dim">NO ATTEMPTS YET</td></tr>'
    unpriced = any(r["cost"] is None and r["status"] != "api_error" for r in rows)
    unpriced_note = " + UNPRICED MODEL CALLS (NO PUBLIC PRICE)" if unpriced else ""
    return ('<div class="panel-title">ATTEMPT LOG</div><table class="log"><thead><tr>'
            '<th>#</th><th>MODEL</th><th>RESULT</th><th>TOKENS</th><th>TIME</th><th>COST</th>'
            f'</tr></thead><tbody>{body}</tbody></table>'
            f'<div class="spent">SESSION COST ${spent:.4f}{unpriced_note}</div>')


WAVE_IDLE = wave.render_history([])


def mk(market_html):
    """Show the market panel only when there is a chart, so no empty box appears."""
    return gr.update(value=market_html, visible=bool(market_html))


def show_spec(label):
    return runner.get_prompt(PRESETS[label]).strip()


def run_agent(label, mode, attempts, request: gr.Request):
    pid = PRESETS[label]
    ok, msg = GUARD.check(client_ip(request))
    if not ok:
        yield banner("BLOCKED", msg, "warn"), render_log([]), mk(""), WAVE_IDLE, "", ""
        return

    cfgs = MODELS[:1] if mode == MODE_NANO else MODELS[:2] if mode == MODE_CASCADE else MODELS[:3]
    messages = [{"role": "system", "content": agent.SYSTEM},
                {"role": "user", "content": runner.get_prompt(pid)}]
    rows, spent, cap_spent, code, sim, wave_html, waves, market_html = [], 0.0, 0.0, "", "", WAVE_IDLE, [], ""
    try:
        for cfg in cfgs:
            for n in range(1, int(attempts) + 1):
                yield (banner("RUNNING", f"{cfg['name'].upper()} ATTEMPT {n}", "run"),
                       render_log(rows, pending=cfg["name"], spent=spent), mk(market_html), wave_html, code, sim)
                start = time.time()
                try:
                    resp = agent.call_model(CLIENT, cfg["id"], messages)
                except Exception:
                    rows.append(dict(model=cfg["name"], status="api_error", tokens=0,
                                     secs=time.time() - start, cost=None))
                    continue
                text = resp.choices[0].message.content or ""
                pt, ct = resp.usage.prompt_tokens, resp.usage.completion_tokens
                usd = agent.cost_usd(cfg, pt, ct)
                spent += usd if usd is not None else 0.0
                cap_spent += usd if usd is not None else (pt + ct) * UNPRICED_CAP_USD_PER_M / 1e6
                code = agent.extract_code(text)
                if code:
                    result = runner.run_candidate(pid, code, want_wave=True)
                else:
                    result = {"status": "no_code", "vcd": "", "feedback":
                              "NO CODE BLOCK IN REPLY (OUTPUT MAY HAVE HIT THE TOKEN LIMIT)"}
                waves.append(dict(model=cfg["name"], status=result["status"], vcd=result.get("vcd", "")))
                wave_html = wave.render_history(waves)
                if pid.startswith("Trade"):  # keep the last good chart if this attempt produced no waveform
                    market_html = market.render_panel(result.get("vcd", "")) or market_html
                rows.append(dict(model=cfg["name"], status=result["status"], tokens=pt + ct,
                                 secs=time.time() - start, cost=usd))
                sim = result["feedback"] or "ALL TESTS PASSED: 0 MISMATCHES"
                if result["status"] == "pass":
                    yield (banner("PASS", f"SOLVED BY {cfg['name'].upper()} IN {len(rows)} CALL(S)", "pass"),
                           render_log(rows, spent=spent), mk(market_html), wave_html, code, sim)
                    return
                messages += [
                    {"role": "assistant", "content": text or "(empty reply)"},
                    {"role": "user", "content": agent.FEEDBACK.format(
                        status=result["status"], details=result["feedback"] or "(none)")},
                ]
        yield (banner("FAIL", "NOT SOLVED WITHIN THE ATTEMPT LIMIT", "fail"),
               render_log(rows, spent=spent), mk(market_html), wave_html, code, sim)
    finally:
        GUARD.add_cost(cap_spent)


CSS = """
:root { --amber:#ffb000; --dim:#8a6200; --line:#4a3500; --green:#33ff66; --red:#ff4d4d; }
/* Force our palette whatever the visitor's OS/browser theme is (Gradio otherwise switches to light colours). */
:root, .dark, .gradio-container {
  color-scheme: dark;
  --body-text-color:#ffb000; --body-text-color-subdued:#8a6200;
  --body-background-fill:#000; --background-fill-primary:#050505; --background-fill-secondary:#000;
  --block-background-fill:#050505; --block-border-color:#4a3500; --border-color-primary:#4a3500;
  --block-title-text-color:#ffb000; --block-label-text-color:#ffb000; --block-label-background-fill:#050505;
  --panel-background-fill:#050505; --panel-border-color:#4a3500;
  --input-background-fill:#000; --input-background-fill-focus:#000; --input-border-color:#4a3500;
  --input-border-color-focus:#ffb000; --input-placeholder-color:#6b4a00; --input-text-color:#ffb000;
  --checkbox-label-background-fill:#140e00; --checkbox-label-background-fill-hover:#241a00;
  --checkbox-label-background-fill-selected:#ffb000; --checkbox-label-border-color:#4a3500;
  --checkbox-label-text-color:#ffb000; --checkbox-label-text-color-selected:#000;
  --button-secondary-background-fill:#140e00; --button-secondary-text-color:#ffb000;
  --button-secondary-border-color:#4a3500;
  --table-even-background-fill:#050505; --table-odd-background-fill:#050505; --table-border-color:#4a3500;
  --neutral-50:#050505; --neutral-100:#0a0a0a; --neutral-200:#4a3500; --neutral-700:#ffb000; --neutral-800:#ffb000;
}
body, .gradio-container, .main, .app { background:#000 !important; color:var(--amber) !important;
  font-family: Consolas, "Lucida Console", "Courier New", monospace !important; }
.block, .form, .gr-group, .panel, .gradio-container .prose { background:#050505 !important;
  border:1px solid var(--line) !important; border-radius:0 !important; box-shadow:none !important; }
label span, .gradio-container label, .gradio-container .prose, .gradio-container p { color:var(--amber) !important;
  font-family: inherit !important; letter-spacing:.06em; text-transform:uppercase; font-size:12px !important; }
textarea, input, select, .wrap, ul.options, .options li { background:#000 !important; color:var(--amber) !important;
  font-family: inherit !important; border-radius:0 !important; border-color:var(--line) !important; }
button { border-radius:0 !important; font-family: inherit !important; letter-spacing:.1em; }
button.primary { background:var(--amber) !important; color:#000 !important; font-weight:700 !important; border:none !important; }
.topbar, .topbar * { color:#000 !important; }
.topbar { background:var(--amber); color:#000; font-weight:700; padding:6px 12px; letter-spacing:.12em;
  display:flex; justify-content:space-between; font-size:13px; }
.banner { padding:10px 12px; font-size:15px; letter-spacing:.08em; border-left:6px solid var(--amber); }
.banner .state { font-weight:700; margin-right:10px; }
.banner.pass { border-color:var(--green); color:var(--green); }
.banner.fail { border-color:var(--red); color:var(--red); }
.banner.run { border-color:var(--amber); }
.banner.warn { border-color:var(--red); color:var(--red); }
.panel-title { color:#000; background:var(--amber); display:inline-block; padding:1px 8px; font-weight:700;
  font-size:12px; letter-spacing:.1em; margin-bottom:6px; }
table.log { width:100%; border-collapse:collapse; font-size:13px; }
table.log th { text-align:left; color:var(--dim); border-bottom:1px solid var(--line); padding:3px 6px; }
table.log td { padding:3px 6px; border-bottom:1px solid #1a1200; }
td.ok { color:var(--green); font-weight:700; } td.bad { color:var(--red); } td.run { color:var(--amber); }
td.dim { color:var(--dim); } .spent { text-align:right; color:var(--dim); font-size:12px; padding-top:4px; }
.foot { color:var(--dim); font-size:11px; letter-spacing:.05em; padding:6px 2px; }
.wave-msg { padding:14px 4px; font-size:12px; letter-spacing:.06em; }
.dim { color:var(--dim); }
/* Make the selected mode button unmistakable: solid amber with dark text. */
.gradio-container label:has(input:checked), .gradio-container label.selected {
  background:var(--amber) !important; border-color:var(--amber) !important; color:#000 !important; }
html body .gradio-container.gradio-container label.selected.selected span,
html body .gradio-container.gradio-container label:has(input:checked) span {
  color:#000 !important; font-weight:700 !important; }
.gradio-container label:has(input[type=radio]) input { opacity:0; width:0; margin:0; position:absolute; }
details.wave-attempt { margin:6px 0 10px; border-top:1px solid var(--line); }
details.wave-attempt summary { cursor:pointer; padding:5px 2px; font-weight:700; letter-spacing:.08em; font-size:12px; }
details.wave-attempt summary.ok { color:var(--green); } details.wave-attempt summary.bad { color:var(--red); }
.bar-row { display:flex; align-items:center; gap:10px; margin:7px 0; font-size:12px; }
.bar-label { width:270px; flex:none; letter-spacing:.05em; }
.bar { flex:1; height:16px; background:#140e00; border:1px solid var(--line); position:relative; }
.bar .range { position:absolute; top:0; bottom:0; background:rgba(255,255,255,.55); }
.bar .fill { height:100%; background:var(--amber); }
.bar-val { width:440px; flex:none; text-align:right; white-space:nowrap; }
.bar-label { width:260px; }
.grid { display:flex; flex-wrap:wrap; gap:3px; max-width:560px; margin:8px 0; }
.cell { display:inline-block; width:15px; height:15px; border:1px solid #000; vertical-align:middle; }
.c-n1 { background:var(--green); } .c-n2 { background:var(--amber); } .c-super { background:#4dd0ff; }
.c-ultra { background:#c77dff; }
.c-cut { background:#7a2a2a; } .c-fail { background:var(--red); }
.legends { display:flex; flex-wrap:wrap; gap:6px 18px; font-size:11px; letter-spacing:.04em; margin:6px 0 10px; }
.legend { white-space:nowrap; }
button[role=tab] { color:var(--amber) !important; background:#000 !important; letter-spacing:.1em; border-radius:0 !important; }
button[role=tab][aria-selected=true] { background:var(--amber) !important; color:#000 !important; font-weight:700 !important; }
.tab-wrapper, .tab-container, .tabs { border-color:var(--line) !important; }
footer { display:none !important; }
"""

with gr.Blocks(title="RTLoop") as demo:
    gr.HTML('<div class="topbar"><span>RTLOOP &gt; VERILOG AGENT</span>'
            '<span>NEMOTRON 3 | NEBIUS TOKEN FACTORY | ICARUS VERILOG 11</span></div>')
    with gr.Tabs():
        with gr.Tab("LIVE AGENT"):
            with gr.Row():
                with gr.Column(scale=2):
                    problem = gr.Dropdown(LABELS, value=LABELS[0], label="PROBLEM", interactive=True)
                    mode = gr.Radio([MODE_NANO, MODE_CASCADE, MODE_ULTRA], value=MODE_CASCADE, label="MODE")
                    attempts = gr.Slider(1, 3, value=2, step=1, label="ATTEMPTS PER MODEL")
                    run_btn = gr.Button("RUN AGENT", variant="primary")
                    spec = gr.Textbox(value=show_spec(LABELS[0]), label="SPEC (WHAT THE MODEL IS ASKED TO BUILD)",
                                      lines=14, interactive=False)
                with gr.Column(scale=3):
                    status = gr.HTML(banner("READY", "SELECT A PROBLEM AND PRESS RUN", "run"))
                    log = gr.HTML(render_log([]))
                    market_out = gr.HTML("", visible=False)
                    wave_out = gr.HTML(WAVE_IDLE)
                    code_out = gr.Textbox(label="CANDIDATE VERILOG", lines=14, interactive=False)
                    sim_out = gr.Textbox(label="SIMULATOR OUTPUT / FEEDBACK TO MODEL", lines=5, interactive=False)
        with gr.Tab("BENCHMARK (151 PROBLEMS)"):
            gr.HTML(bench_view.build_html())
    gr.HTML('<div class="foot">GENERATED CODE IS RUN IN A SIMULATOR. DEMO IS RATE-LIMITED AND CAPPED. '
            'BENCHMARK: NVIDIA VERILOGEVAL. SOURCE: GITHUB.COM/KARTAHUGHES/RTLOOP</div>')

    problem.change(show_spec, problem, spec)
    run_btn.click(run_agent, [problem, mode, attempts], [status, log, market_out, wave_out, code_out, sim_out])

demo.queue(default_concurrency_limit=4, max_size=20)

if __name__ == "__main__":
    demo.launch(css=CSS, server_name="0.0.0.0", server_port=int(os.environ.get("PORT", "7860")))
