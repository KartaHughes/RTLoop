"""Render a reference-vs-candidate timing diagram from a simulator VCD dump, as inline SVG.

Signals named <x>_ref and <x>_dut (VerilogEval's convention, also used by our
custom testbenches) are drawn as a pair; mismatches are shaded red.
"""
import bisect
import html

LABEL_W, PLOT_W, ROW_H, AXIS_H = 190, 720, 24, 22
AMBER, GREEN, DUT, RED, DIM = "#ffb000", "#33ff66", "#ffe08a", "#ff4d4d", "#6b4a00"
MAX_ROWS = 16


def parse_vcd(text):
    """Return {name: {"width": int, "changes": [(time, value_string)]}}."""
    ids, sigs, t, in_header = {}, {}, 0, True
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if in_header:
            if line.startswith("$var"):
                parts = line.split()
                width, ident, name = int(parts[2]), parts[3], parts[4]
                if ident in ids:
                    continue
                if name in sigs:
                    ids[ident] = None
                else:
                    ids[ident] = name
                    sigs[name] = {"width": width, "changes": []}
            elif line.startswith("$enddefinitions"):
                in_header = False
            continue
        if line[0] == "#":
            t = int(line[1:])
        elif line[0] in "bB":
            val, _, ident = line[1:].partition(" ")
            name = ids.get(ident.strip())
            if name:
                sigs[name]["changes"].append((t, val.lower()))
        elif line[0] in "01xXzZ" and not line.startswith("$"):
            name = ids.get(line[1:])
            if name:
                sigs[name]["changes"].append((t, line[0].lower()))
    return sigs


def value_at(sig, t):
    times = [c[0] for c in sig["changes"]]
    i = bisect.bisect_right(times, t) - 1
    return sig["changes"][i][1] if i >= 0 else "x"


def to_hex(val, width):
    if "x" in val or "z" in val:
        return "x"
    return format(int(val, 2), "X") if width > 1 else val


def differ(a, b):
    """Reference x matches anything; a candidate x only matches x."""
    return a != "x" and a != b


def window(sigs):
    """Pick a time window: around the first mismatch, else the first ~30 cycles."""
    pairs = pair_names(sigs)
    mm_times = mismatch_times(sigs, pairs)
    end = max((c[0] for s in sigs.values() for c in s["changes"]), default=0)
    if mm_times:
        first = mm_times[0]
        return max(0, first - 40), min(end, first + 140) or first + 140
    return 0, max(40, min(end, 300))


def pair_names(sigs):
    return [n[:-4] for n in sigs if n.endswith("_ref") and n[:-4] + "_dut" in sigs]


def mismatch_times(sigs, pairs):
    """Times at which any reference/candidate pair differs."""
    times = sorted({c[0] for p in pairs for suf in ("_ref", "_dut") for c in sigs[p + suf]["changes"]})
    return [t for t in times if any(
        differ(value_at(sigs[p + "_ref"], t), value_at(sigs[p + "_dut"], t)) for p in pairs)]


def render(vcd_text):
    """SVG string, or '' if there is nothing to draw."""
    try:
        sigs = parse_vcd(vcd_text)
    except (ValueError, IndexError):
        return ""
    pairs = pair_names(sigs)
    if not pairs:
        return ""
    start, stop = window(sigs)
    if stop <= start:
        return ""

    skip = {"tb_mismatch"} | {p + s for p in pairs for s in ("_ref", "_dut")}
    rows = [("clk", "clk", AMBER)] if "clk" in sigs else []
    rows += [(n, n, AMBER) for n in sigs if n not in skip and n != "clk"]
    for p in pairs:
        rows.append((p + "_ref", f"{p} (REF)", GREEN))
        rows.append((p + "_dut", f"{p} (YOURS)", DUT))
    rows = rows[:MAX_ROWS]

    def x(t):
        return LABEL_W + (min(max(t, start), stop) - start) / (stop - start) * PLOT_W

    height = AXIS_H + ROW_H * len(rows) + 6
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {LABEL_W + PLOT_W + 10} {height}" '
           f'width="100%" font-family="Consolas, monospace" font-size="11">',
           f'<rect width="100%" height="100%" fill="#000"/>']

    # Mismatch shading, drawn first so signals sit on top.
    mt = mismatch_times(sigs, pairs)
    all_times = sorted({c[0] for p in pairs for suf in ("_ref", "_dut") for c in sigs[p + suf]["changes"]} | {stop})
    for t0, t1 in zip(all_times, all_times[1:] + [stop]):
        if t0 in mt and t1 > start and t0 < stop:
            out.append(f'<rect x="{x(t0):.1f}" y="{AXIS_H}" width="{max(x(t1) - x(t0), 2):.1f}" '
                       f'height="{height - AXIS_H}" fill="{RED}" opacity="0.22"/>')

    # Time axis.
    step = 50 if (stop - start) > 150 else 10
    t = (start // step + 1) * step
    while t < stop:
        out.append(f'<line x1="{x(t):.1f}" y1="{AXIS_H - 4}" x2="{x(t):.1f}" y2="{height}" stroke="#1a1200"/>')
        out.append(f'<text x="{x(t) + 2:.1f}" y="12" fill="{DIM}">{t}ps</text>')
        t += step

    for r, (key, label, color) in enumerate(rows):
        sig = sigs[key]
        top = AXIS_H + r * ROW_H
        out.append(f'<text x="6" y="{top + 16}" fill="{color}">{html.escape(label)}</text>')
        change_times = [c[0] for c in sig["changes"] if start < c[0] < stop]
        edges = [start] + change_times + [stop]
        for a, b in zip(edges, edges[1:]):
            val = value_at(sig, a)
            xa, xb = x(a), x(b)
            if sig["width"] == 1:
                y = top + (5 if val == "1" else 19)
                col = DIM if val in ("x", "z") else color
                out.append(f'<line x1="{xa:.1f}" y1="{y}" x2="{xb:.1f}" y2="{y}" stroke="{col}" stroke-width="1.6"/>')
                out.append(f'<line x1="{xb:.1f}" y1="{top + 5}" x2="{xb:.1f}" y2="{top + 19}" stroke="{col}" stroke-width="1" opacity="0.5"/>')
            else:
                hexv = to_hex(val, sig["width"])
                col = DIM if hexv == "x" else color
                out.append(f'<rect x="{xa:.1f}" y="{top + 5}" width="{max(xb - xa - 1, 1):.1f}" height="14" '
                           f'fill="none" stroke="{col}" stroke-width="1"/>')
                if xb - xa > 8 * len(hexv) + 6:
                    out.append(f'<text x="{(xa + xb) / 2:.1f}" y="{top + 16}" fill="{col}" text-anchor="middle">{hexv}</text>')
    out.append("</svg>")
    return "".join(out)


def render_body(vcd_text, status):
    if status == "compile_error":
        return '<div class="dim wave-msg">NO WAVEFORM: THE CODE DID NOT COMPILE.</div>'
    svg = render(vcd_text) if vcd_text else ""
    if not svg:
        return '<div class="dim wave-msg">NO WAVEFORM AVAILABLE FOR THIS ATTEMPT.</div>'
    note = ("RED SHADING = WHERE THE CANDIDATE DIFFERS FROM THE REFERENCE" if status != "pass"
            else "THE CANDIDATE MATCHES THE REFERENCE (FIRST CYCLES SHOWN; THE VERDICT COVERS THE WHOLE TEST)")
    return f'{svg}<div class="spent">{note}</div>'


def render_history(attempts):
    """Panel with one collapsible waveform per attempt, oldest first.

    attempts: list of dicts with model, status, vcd.
    """
    title = '<div class="panel-title">WAVEFORMS: REFERENCE VS CANDIDATE, ONE PER ATTEMPT</div>'
    if not attempts:
        return title + '<div class="dim wave-msg">RUN THE AGENT TO SEE THE SIMULATED SIGNALS.</div>'
    parts = []
    for i, a in enumerate(attempts, 1):
        cls = "ok" if a["status"] == "pass" else "bad"
        head = html.escape(f'ATTEMPT {i} | {a["model"].upper()} | {a["status"].upper()}')
        parts.append(f'<details open class="wave-attempt"><summary class="{cls}">{head}</summary>'
                     f'{render_body(a.get("vcd", ""), a["status"])}</details>')
    return title + "".join(parts)
