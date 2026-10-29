"""Market view for the trading problem: bid and ask over time, built from the simulation's VCD dump.

The stored quotes are rebuilt from the testbench inputs exactly as the reference
circuit stores them. Amber shading marks when the reference says the book is
crossed (bid >= ask); red marks where the candidate's `crossed` output disagrees.
"""
import html

import wave

W, H = 940, 250
LEFT, RIGHT, TOP, BOTTOM = 56, 12, 16, 30
BID, ASK, AMBER, RED, DIM = "#33ff66", "#4dd0ff", "#ffb000", "#ff4d4d", "#6b4a00"
NEEDED = ("clk", "reset", "bid_valid", "bid_price", "ask_valid", "ask_price", "crossed_ref", "crossed_dut")


def to_int(v):
    return None if ("x" in v or "z" in v) else int(v, 2)


def quote_history(sigs, end_t):
    """[(time, bid, have_bid, ask, have_ask)] after each rising edge up to end_t."""
    edges = [t for t, v in sigs["clk"]["changes"] if v == "1" and t <= end_t]
    bid = ask = 0
    hb = ha = False
    out = []
    for t in edges:
        def at(name):
            return wave.value_at(sigs[name], t - 1)  # value just before the edge
        if at("reset") == "1":
            bid = ask = 0
            hb = ha = False
        else:
            if at("bid_valid") == "1" and to_int(at("bid_price")) is not None:
                bid, hb = to_int(at("bid_price")), True
            if at("ask_valid") == "1" and to_int(at("ask_price")) is not None:
                ask, ha = to_int(at("ask_price")), True
        out.append((t, bid, hb, ask, ha))
    return out


def chart_end(sigs):
    """Stop before the extreme-price tests so the interesting range stays readable."""
    extremes = [t for name in ("bid_price", "ask_price") for t, v in sigs[name]["changes"]
                if to_int(v) is not None and to_int(v) >= 60000]
    if extremes:
        return min(extremes)
    return max(c[0] for s in sigs.values() for c in s["changes"])


def render(vcd_text):
    try:
        sigs = wave.parse_vcd(vcd_text)
    except (ValueError, IndexError):
        return ""
    if any(n not in sigs for n in NEEDED):
        return ""
    end_t = chart_end(sigs)
    hist = quote_history(sigs, end_t)
    if len(hist) < 3:
        return ""
    t_end = hist[-1][0] + 10
    prices = [p for _, b, hb, a, ha in hist for p, h in ((b, hb), (a, ha)) if h]
    ymax = max(prices + [10]) * 1.18

    def x(t):
        return LEFT + t / t_end * (W - LEFT - RIGHT)

    def y(p):
        return TOP + (1 - p / ymax) * (H - TOP - BOTTOM)

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" '
           'font-family="Consolas, monospace" font-size="11"><rect width="100%" height="100%" fill="#000"/>']

    # Gridlines and price labels.
    step = 50 if ymax <= 400 else 100 if ymax <= 800 else 500
    p = 0
    while p <= ymax:
        out.append(f'<line x1="{LEFT}" y1="{y(p):.1f}" x2="{W - RIGHT}" y2="{y(p):.1f}" stroke="#1a1200"/>')
        out.append(f'<text x="{LEFT - 6}" y="{y(p) + 4:.1f}" fill="{DIM}" text-anchor="end">{p}</text>')
        p += step

    # Shading: reference crossed (amber), candidate disagreement (red).
    times = [h[0] for h in hist] + [t_end]
    for t0, t1 in zip(times, times[1:]):
        ref = wave.value_at(sigs["crossed_ref"], t0 + 1)
        dut = wave.value_at(sigs["crossed_dut"], t0 + 1)
        if ref == "1":
            out.append(f'<rect x="{x(t0):.1f}" y="{TOP}" width="{x(t1) - x(t0):.1f}" height="{H - TOP - BOTTOM}" '
                       f'fill="{AMBER}" opacity="0.16"/>')
        if wave.differ(ref, dut):
            out.append(f'<rect x="{x(t0):.1f}" y="{TOP}" width="{x(t1) - x(t0):.1f}" height="{H - TOP - BOTTOM}" '
                       f'fill="{RED}" opacity="0.35"/>')

    # Bid and ask as step lines, with the spread labelled when the book is not crossed.
    # Merge consecutive cycles with identical quotes into runs, so each stretch is drawn and labelled once.
    runs = []
    for i, (t0, b, hb, a, ha) in enumerate(hist):
        t1 = hist[i + 1][0] if i + 1 < len(hist) else t_end
        if runs and tuple(runs[-1][1:5]) == (b, hb, a, ha):
            runs[-1][5] = t1
        else:
            runs.append([t0, b, hb, a, ha, t1])
    for idx, (t0, b, hb, a, ha, t1) in enumerate(runs):
        nxt = runs[idx + 1] if idx + 1 < len(runs) else None
        for price, have, color, ni in ((b, hb, BID, 1), (a, ha, ASK, 3)):
            if have:
                out.append(f'<line x1="{x(t0):.1f}" y1="{y(price):.1f}" x2="{x(t1):.1f}" y2="{y(price):.1f}" '
                           f'stroke="{color}" stroke-width="2.4"/>')
                if nxt and nxt[ni + 1] and nxt[ni] != price:
                    out.append(f'<line x1="{x(t1):.1f}" y1="{y(price):.1f}" x2="{x(t1):.1f}" y2="{y(nxt[ni]):.1f}" '
                               f'stroke="{color}" stroke-width="1.2" opacity="0.6"/>')
        if hb and ha and x(t1) - x(t0) > 60:
            if a > b:
                out.append(f'<text x="{(x(t0) + x(t1)) / 2:.1f}" y="{(y(a) + y(b)) / 2 - 5:.1f}" fill="{AMBER}" '
                           f'text-anchor="middle">spread {a - b}</text>')
            else:
                out.append(f'<text x="{(x(t0) + x(t1)) / 2:.1f}" y="{TOP + 12}" fill="{AMBER}" '
                           f'text-anchor="middle">CROSSED</text>')

    # Time axis and legend.
    for t in range(0, int(t_end), 50):
        out.append(f'<text x="{x(t) + 2:.1f}" y="{H - 12}" fill="{DIM}">{t}ps</text>')
    out.append(f'<text x="{LEFT + 6}" y="{H - 2}" fill="{BID}">BID (best buyer)</text>')
    out.append(f'<text x="{LEFT + 150}" y="{H - 2}" fill="{ASK}">ASK (best seller)</text>')
    out.append(f'<text x="{LEFT + 300}" y="{H - 2}" fill="{AMBER}">AMBER = CROSSED (REFERENCE)</text>')
    out.append(f'<text x="{LEFT + 500}" y="{H - 2}" fill="{RED}">RED = YOUR CIRCUIT DISAGREED</text>')
    out.append("</svg>")
    return "".join(out)


def render_panel(vcd_text):
    """HTML for the demo page, or '' when there is nothing to draw."""
    svg = render(vcd_text) if vcd_text else ""
    if not svg:
        return ""
    explain = ("BID = THE HIGHEST PRICE A BUYER OFFERS. ASK = THE LOWEST PRICE A SELLER WANTS. WHEN THE BID REACHES "
               "THE ASK THE BOOK IS CROSSED AND A TRADE COULD HAPPEN. THE LINES ARE REBUILT FROM THE QUOTES FED TO "
               "THE CIRCUIT; SHADING COMES FROM THE SIMULATION. THIS SHOWS THE EARLY, READABLE PART OF THE TEST; "
               "MISMATCHES LATER IN THE TEST (EXTREME PRICES, RANDOM PHASE) APPEAR IN THE WAVEFORM BELOW.")
    return (f'<div class="panel-title">MARKET VIEW: TOP OF BOOK</div>{svg}'
            f'<div class="spent" style="text-align:left">{html.escape(explain)}</div>')
