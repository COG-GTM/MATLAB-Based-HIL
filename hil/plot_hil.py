#!/usr/bin/env python3
"""Plots + HTML report from simulink_standin.py JSON results."""
import base64, json, math, os, re, sys
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

out = sys.argv[1]
plt.style.use("dark_background")
plt.rcParams.update({"font.size": 14, "axes.titlesize": 18, "axes.titleweight": "bold", "figure.facecolor": "#0d1117", "axes.facecolor": "#0d1117"})
C_OK, C_BAD, C_REF, C_ACC = "#3fb950", "#f85149", "#8b949e", "#58a6ff"
load = lambda n: json.load(open(f"{out}/{n}.json")) if os.path.exists(f"{out}/{n}.json") else None
ac, af, bc, bf = load("after_clean"), load("after_faults"), load("before_clean"), load("before_faults")
pngs = []

# 1. latency timeline + histogram (clean run, fixed firmware)
r = ac
ks = sorted(int(k) for k in r["rtt_ms"]); v = [r["rtt_ms"][str(k)] for k in ks]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(16, 6.5), gridspec_kw={"width_ratios": [2.2, 1]})
a1.plot(ks, v, "o-", color=C_ACC, ms=3, lw=1)
a1.axhline(50, color=C_REF, ls="--"); a1.text(ks[-1], 51, "50 ms sample time", ha="right", color=C_REF)
a1.set(xlabel="packet #", ylabel="round-trip latency [ms]", title="Packet timeline: host -> simavr ATmega328P -> host", ylim=(0, 70))
a2.hist(v, bins=25, color=C_ACC, orientation="horizontal"); a2.set(ylim=(0, 70), xlabel="count", title="Latency histogram")
a2.axhline(r["rtt_mean"], color=C_OK, lw=2)
a2.text(a2.get_xlim()[1] * 0.97, 62, f"mean {r['rtt_mean']:.1f} ms\np99 {r['rtt_p99']:.1f} ms\nmin {min(v):.1f} ms", ha="right", va="top", color=C_OK, fontsize=15, fontweight="bold")
if r["lost_superseded"]:
    kw = r["lost_superseded"][0]
    a1.annotate(f"phase wrap: pkt {kw} superseded\n(host and target 50 ms clocks drift)", (kw, 28), xytext=(kw - 125, 60),
                color="#d29922", fontsize=13, arrowprops=dict(arrowstyle="->", color="#d29922"))
a1.text(ks[-1], 18, f"floor {min(v):.1f} ms = 2 x 14 B @115200 + loop", ha="right", color=C_REF, fontsize=12)
fig.suptitle(f"{r['packets_echoed']}/{r['packets_sent']} packets echoed | {r['rx_frames_per_s']:.1f} frames/s | "
             f"{r['rx_bytes_per_s']:.0f} B/s per direction | 115200 baud, real-time simavr", color=C_REF, y=0.02, fontsize=13)
fig.tight_layout(rect=(0, 0.05, 1, 1)); p = f"{out}/hil_latency.png"; fig.savefig(p, dpi=110); pngs.append(p); plt.close(fig)

# 2. before/after fault injection timeline
if bf:
    fig, axs = plt.subplots(2, 1, figsize=(16, 9), sharex=True)
    for ax, r, name in [(axs[0], bf, "BEFORE (main): header-only sync"), (axs[1], af, "AFTER: header+terminator framing with resync")]:
        tx = {int(k): v for k, v in r["tx"].items()}
        ax.plot([tx[k][0] for k in sorted(tx)], [10 * math.sin(2 * math.pi * k / 40) for k in sorted(tx)], color=C_REF, lw=1, label="Simulink command (sent)")
        ok = [p for p in r["timeline"] if p["ok"]]
        ax.plot([p["t"] for p in ok], [p["v"][1] for p in ok], ".", color=C_OK, ms=5, label="target echo (valid)")
        for i, p in enumerate(r["phantoms"]):
            y = p["v"][1]; yplot = y if y is not None and abs(y) < 14 else 13
            ax.plot(p["t"], yplot, "X", color=C_BAD, ms=16, mec="white")
            ax.annotate("corrupt committed:\n(" + ", ".join("NaN" if x is None else f"{x:.2g}" for x in p["v"]) + ")",
                        (p["t"], yplot), xytext=(-60 if i == 1 else 10, -45 if i != 1 else 45), textcoords="offset points",
                        color=C_BAD, fontsize=11, fontweight="bold", ha="right" if i == 1 else "left")
        for fr in r["fault_rows"]:
            ax.axvline(fr["t"], color="#d29922", ls=":", lw=1.5)
        ax.set(ylim=(-14, 16), ylabel="value2"); ax.set_title(name, loc="left", color=C_BAD if r is bf else C_OK)
        n_col = len(r["lost_collateral"])
        ax.text(0.995, 0.04, f"corrupt frames committed: {r['phantom_frames']}   good packets lost: {n_col}", transform=ax.transAxes,
                ha="right", fontsize=15, fontweight="bold", color=C_BAD if r["phantom_frames"] + n_col else C_OK)
    for i, fr in enumerate(af["fault_rows"]):
        axs[0].text(fr["t"], 15.2 if i % 2 == 0 else 13.0, fr["fault"], ha="center", fontsize=11, color="#d29922")
    axs[0].legend(loc="lower left", fontsize=11); axs[1].set_xlabel("time [s]")
    fig.suptitle("UART fault injection: garbage injected -> recovered", fontsize=20, fontweight="bold")
    fig.tight_layout(); p = f"{out}/hil_fault_recovery.png"; fig.savefig(p, dpi=110); pngs.append(p); plt.close(fig)

    # 3. scorecard
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(16, 6.5), gridspec_kw={"width_ratios": [2, 1]})
    labels = [fr["fault"] for fr in af["fault_rows"]]
    bad = lambda r: [fr["corrupt_frames_committed"] + fr["good_packets_lost_after"] for fr in r["fault_rows"]]
    y = range(len(labels)); h = 0.38
    a1.barh([i + h / 2 for i in y], bad(bf), h, color=C_BAD, label="before (main)")
    a1.barh([i - h / 2 for i in y], bad(af), h, color=C_OK, label="after (fix)")
    a1.set_yticks(list(y)); a1.set_yticklabels(labels); a1.invert_yaxis()
    a1.set(xlabel="corrupt frames committed + good packets lost", title="Robustness per injected fault"); a1.legend(loc="lower right")
    for i, (b0, b1) in enumerate(zip(bad(bf), bad(af))):
        a1.text(0.03, i - h / 2, " 0 - clean resync" if b0 else " 0 / 0 - handled by both", va="center", color=C_OK if b0 else C_REF, fontsize=12)
    sizes = {}
    for n in ("before", "after"):
        t = open(f"{out}/size_{n}.txt").read()
        sizes[n] = [int(re.search(r"uses (\d+) bytes .*program", t).group(1)), int(re.search(r"Global variables use (\d+)", t).group(1))]
    a2.bar([0, 1], [sizes["before"][0], sizes["after"][0]], color=[C_REF, C_ACC], width=0.6)
    for i, n in enumerate(("before", "after")):
        a2.text(i, sizes[n][0] + 40, f"{sizes[n][0]} B flash\n{sizes[n][1]} B RAM", ha="center", fontsize=13)
    a2.set_xticks([0, 1]); a2.set_xticklabels(["before", "after"]); a2.set_ylim(0, 2600)
    a2.set(title="arduino:avr:uno footprint", ylabel="flash bytes (of 32256)")
    tot_b = bf["phantom_frames"] + len(bf["lost_collateral"]); tot_a = af["phantom_frames"] + len(af["lost_collateral"])
    fig.suptitle(f"Fault scorecard: {tot_b} bad outcomes -> {tot_a}  |  cost: +{sizes['after'][0]-sizes['before'][0]} B flash, +{sizes['after'][1]-sizes['before'][1]} B RAM", fontsize=19, fontweight="bold")
    fig.tight_layout(); p = f"{out}/hil_scorecard.png"; fig.savefig(p, dpi=110); pngs.append(p); plt.close(fig)

# HTML report
rows = "".join(f"<tr><td>{r['label']}{' + faults' if r['faults'] else ''}</td><td>{r['packets_sent']}</td><td>{r['packets_echoed']}</td>"
               f"<td>{r['phantom_frames']}</td><td>{len(r['lost_collateral'])}</td><td>{len(r['lost_superseded'])}</td>"
               f"<td>{r['rtt_mean']:.1f}</td><td>{r['rtt_p99']:.1f}</td><td>{r['rx_frames_per_s']:.1f}</td></tr>"
               for r in (bc, bf, ac, af) if r)
imgs = "".join(f'<img src="data:image/png;base64,{base64.b64encode(open(p,"rb").read()).decode()}">' for p in pngs)
open(f"{out}/report.html", "w").write(f"""<!doctype html><html><head><meta charset=utf-8><title>MATLAB-Based-HIL software HIL report</title>
<style>body{{background:#0d1117;color:#e6edf3;font:16px sans-serif;margin:24px}}img{{width:100%;max-width:1400px;margin:12px 0;border:1px solid #30363d}}
table{{border-collapse:collapse}}td,th{{border:1px solid #30363d;padding:6px 12px;text-align:right}}h1{{color:#58a6ff}}</style></head><body>
<h1>Software HIL: Simulink stand-in &harr; ATmega328P firmware (simavr)</h1>
<p>Real arduino:avr:uno ELF executed in simavr at real-time 16 MHz; UART0 bridged to a PTY at 115200 baud; pyserial host speaks the Simulink
Serial Send/Receive byte protocol ('x'+3&times;float32+'\\n' &rarr; 'A'+3&times;float32+'\\n', 50 ms).</p>
<table><tr><th>run</th><th>sent</th><th>echoed</th><th>corrupt committed</th><th>lost (fault collateral)</th><th>superseded (rate)</th><th>RTT mean ms</th><th>RTT p99 ms</th><th>frames/s</th></tr>{rows}</table>
{imgs}</body></html>""")
print("wrote", *pngs, f"{out}/report.html")
