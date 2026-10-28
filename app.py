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
import runner
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
    return ('<div class="panel-title">ATTEMPT LOG</div><table class="log"><thead><tr>'
            '<th>#</th><th>MODEL</th><th>RESULT</th><th>TOKENS</th><th>TIME</th><th>COST</th>'
            f'</tr></thead><tbody>{body}</tbody></table>'
            f'<div class="spent">SESSION COST ${spent:.4f}</div>')


def show_spec(label):
    return runner.get_prompt(PRESETS[label]).strip()


def run_agent(label, mode, attempts, request: gr.Request):
    pid = PRESETS[label]
    ok, msg = GUARD.check(client_ip(request))
    if not ok:
        yield banner("BLOCKED", msg, "warn"), render_log([]), "", ""
        return

    cfgs = MODELS[:1] if mode == MODE_NANO else MODELS[:2]
    messages = [{"role": "system", "content": agent.SYSTEM},
                {"role": "user", "content": runner.get_prompt(pid)}]
    rows, spent, code, sim = [], 0.0, "", ""
    try:
        for cfg in cfgs:
            for n in range(1, int(attempts) + 1):
                yield (banner("RUNNING", f"{cfg['name'].upper()} ATTEMPT {n}", "run"),
                       render_log(rows, pending=cfg["name"], spent=spent), code, sim)
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
                spent += usd or 0.0
                code = agent.extract_code(text)
                if code:
                    result = runner.run_candidate(pid, code)
                else:
                    result = {"status": "no_code", "feedback":
                              "NO CODE BLOCK IN REPLY (OUTPUT MAY HAVE HIT THE TOKEN LIMIT)"}
                rows.append(dict(model=cfg["name"], status=result["status"], tokens=pt + ct,
                                 secs=time.time() - start, cost=usd))
                sim = result["feedback"] or "ALL TESTS PASSED: 0 MISMATCHES"
                if result["status"] == "pass":
                    yield (banner("PASS", f"SOLVED BY {cfg['name'].upper()} IN {len(rows)} CALL(S)", "pass"),
                           render_log(rows, spent=spent), code, sim)
                    return
                messages += [
                    {"role": "assistant", "content": text or "(empty reply)"},
                    {"role": "user", "content": agent.FEEDBACK.format(
                        status=result["status"], details=result["feedback"] or "(none)")},
                ]
        yield (banner("FAIL", "NOT SOLVED WITHIN THE ATTEMPT LIMIT", "fail"),
               render_log(rows, spent=spent), code, sim)
    finally:
        GUARD.add_cost(spent)


CSS = """
:root { --amber:#ffb000; --dim:#8a6200; --line:#4a3500; --green:#33ff66; --red:#ff4d4d; }
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
footer { display:none !important; }
"""

with gr.Blocks(title="RTLoop") as demo:
    gr.HTML('<div class="topbar"><span>RTLOOP &gt; VERILOG AGENT</span>'
            '<span>NEMOTRON 3 | NEBIUS TOKEN FACTORY | ICARUS VERILOG 11</span></div>')
    with gr.Row():
        with gr.Column(scale=2):
            problem = gr.Dropdown(LABELS, value=LABELS[0], label="PROBLEM", interactive=True)
            mode = gr.Radio([MODE_NANO, MODE_CASCADE], value=MODE_CASCADE, label="MODE")
            attempts = gr.Slider(1, 3, value=2, step=1, label="ATTEMPTS PER MODEL")
            run_btn = gr.Button("RUN AGENT", variant="primary")
            spec = gr.Textbox(value=show_spec(LABELS[0]), label="SPEC (WHAT THE MODEL IS ASKED TO BUILD)",
                              lines=14, interactive=False)
        with gr.Column(scale=3):
            status = gr.HTML(banner("READY", "SELECT A PROBLEM AND PRESS RUN", "run"))
            log = gr.HTML(render_log([]))
            code_out = gr.Textbox(label="CANDIDATE VERILOG", lines=14, interactive=False)
            sim_out = gr.Textbox(label="SIMULATOR OUTPUT / FEEDBACK TO MODEL", lines=5, interactive=False)
    gr.HTML('<div class="foot">GENERATED CODE IS RUN IN A SIMULATOR. DEMO IS RATE-LIMITED AND CAPPED. '
            'BENCHMARK: NVIDIA VERILOGEVAL. SOURCE: GITHUB.COM/KARTAHUGHES/RTLOOP</div>')

    problem.change(show_spec, problem, spec)
    run_btn.click(run_agent, [problem, mode, attempts], [status, log, code_out, sim_out])

demo.queue(default_concurrency_limit=4, max_size=20)

if __name__ == "__main__":
    demo.launch(css=CSS, server_name="0.0.0.0", server_port=int(os.environ.get("PORT", "7860")))
