#!/usr/bin/env python3
"""Host-side stand-in for the Simulink side of the MATLAB-Based-HIL serial link.

Implements the exact packet contract used by multiple_send_receive.ino:
  host -> MCU : 'x' + 3 x float32 (little-endian) + '\n'   (13 bytes)
  MCU  -> host: 'A' + 3 x float32 (little-endian) + '\n'   (13 bytes)
  115200 baud, one packet every 50 ms.

The three floats carry a simulated plant (2nd-order mass-spring-damper driven by
a step): [setpoint, position, velocity]. The MCU end echoes them back, and this
script measures round-trip latency, decodes the floats, and produces plots.
"""
import argparse
import json
import os
import struct
import sys
import time

import serial

HDR_TX, HDR_RX, TERM = b"x", b"A", b"\n"
PKT = struct.Struct("<3f")
PERIOD_S = 0.050


def plant_step(t):
    """Analytic under-damped 2nd-order step response (wn=4 rad/s, zeta=0.3)."""
    import math
    wn, z = 4.0, 0.3
    wd = wn * math.sqrt(1 - z * z)
    e = math.exp(-z * wn * t)
    pos = 1 - e * (math.cos(wd * t) + (z * wn / wd) * math.sin(wd * t))
    vel = (wn * wn / wd) * e * math.sin(wd * t)
    return 1.0, pos, vel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", required=True)
    ap.add_argument("--duration", type=float, default=6.0)
    ap.add_argument("--out", default="demo/out")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    ser = serial.Serial(args.port, 115200, timeout=0)
    ser.reset_input_buffer()

    pending = {}   # raw 12-byte payload -> send time
    log = []       # rows: t, sp, pos, vel, rx_sp, rx_pos, rx_vel, latency_ms
    rx_buf = b""
    sent = received = bad_frames = 0
    t0 = time.perf_counter()
    next_tx = t0
    print(f"{'t[s]':>6} {'sent (sp,pos,vel)':>28} {'echoed (sp,pos,vel)':>28} {'RTT[ms]':>8}")
    while True:
        now = time.perf_counter()
        if now >= next_tx:
            t = now - t0
            if t > args.duration:
                break
            payload = PKT.pack(*plant_step(t))
            ser.write(HDR_TX + payload + TERM)
            pending[payload] = (now, t)
            sent += 1
            next_tx += PERIOD_S
        rx_buf += ser.read(256)
        while len(rx_buf) >= 14:
            if rx_buf[0:1] != HDR_RX:
                rx_buf = rx_buf[1:]
                bad_frames += 1
                continue
            frame, rx_buf = rx_buf[:14], rx_buf[14:]
            if frame[13:14] != TERM:
                bad_frames += 1
                continue
            payload = frame[1:13]
            vals = PKT.unpack(payload)
            trx = time.perf_counter()
            if payload in pending:
                tsend, t = pending.pop(payload)
                lat = (trx - tsend) * 1e3
                received += 1
                s = PKT.unpack(payload)
                log.append((t, *s, *vals, lat))
                if received % 10 == 1:
                    print(f"{t:6.2f} {str(tuple(round(x,3) for x in s)):>28} "
                          f"{str(tuple(round(x,3) for x in vals)):>28} {lat:8.2f}")
        time.sleep(0.001)
    ser.close()

    lats = [r[-1] for r in log]
    summary = {
        "packets_sent": sent,
        "packets_echoed": received,
        "packets_superseded_by_newer": sent - received,
        "bad_frames": bad_frames,
        "float_mismatches": sum(1 for r in log if r[1:4] != r[4:7]),
        "rtt_ms_min": min(lats), "rtt_ms_mean": sum(lats) / len(lats), "rtt_ms_max": max(lats),
        "baud": 115200, "period_ms": 50, "frame_bytes": 14,
    }
    print("\nSUMMARY", json.dumps(summary, indent=2))
    with open(os.path.join(args.out, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    with open(os.path.join(args.out, "packets.csv"), "w") as f:
        f.write("t,sp,pos,vel,rx_sp,rx_pos,rx_vel,rtt_ms\n")
        for r in log:
            f.write(",".join(f"{x:.6f}" for x in r) + "\n")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    t = [r[0] for r in log]
    fig, ax = plt.subplots(3, 1, figsize=(10, 8), sharex=True)
    for i, (name, c) in enumerate([("setpoint", "k"), ("position", "tab:blue"), ("velocity", "tab:orange")]):
        ax[i].plot(t, [r[1 + i] for r in log], c, lw=2, label=f"{name} sent (Simulink side)")
        ax[i].plot(t, [r[4 + i] for r in log], "o", ms=4, mfc="none", c="tab:red", label=f"{name} echoed by MCU")
        ax[i].set_ylabel(name); ax[i].grid(alpha=.3); ax[i].legend(loc="best", fontsize=8)
    ax[0].set_title("Plant signals over the 'x'/'A' float packet link  —  115200 baud, 50 ms cadence")
    ax[2].set_xlabel("time [s]")
    fig.tight_layout(); fig.savefig(os.path.join(args.out, "sent_vs_received.png"), dpi=130)

    fig, ax = plt.subplots(1, 2, figsize=(10, 4))
    ax[0].hist(lats, bins=25, color="tab:green", edgecolor="k")
    ax[0].set_xlabel("round-trip latency [ms]"); ax[0].set_ylabel("packets")
    ax[0].set_title(f"RTT histogram (n={received}, mean {summary['rtt_ms_mean']:.1f} ms)")
    ax[1].plot(t, lats, ".-", c="tab:green"); ax[1].axhline(50, ls="--", c="gray", label="50 ms loop period")
    ax[1].set_xlabel("time [s]"); ax[1].set_ylabel("RTT [ms]"); ax[1].legend(); ax[1].grid(alpha=.3)
    fig.tight_layout(); fig.savefig(os.path.join(args.out, "latency.png"), dpi=130)

    # Packet anatomy figure
    fig, ax = plt.subplots(figsize=(10, 2.6))
    ex = HDR_TX + PKT.pack(*plant_step(1.0)) + TERM
    labels = ["hdr 'x'"] + [f"f{i//4+1}[{i%4}]" for i in range(12)] + ["'\\n'"]
    cols = ["gold"] + ["lightblue"] * 4 + ["lightgreen"] * 4 + ["thistle"] * 4 + ["salmon"]
    for i, (b, l, c) in enumerate(zip(ex, labels, cols)):
        ax.add_patch(plt.Rectangle((i, 0), 1, 1, fc=c, ec="k"))
        ax.text(i + .5, .62, f"0x{b:02X}", ha="center", va="center", fontsize=9, family="monospace")
        ax.text(i + .5, .25, l, ha="center", va="center", fontsize=7)
    ax.set_xlim(0, 14); ax.set_ylim(0, 1); ax.axis("off")
    ax.set_title("14-byte frame: header + 3 x float32 (LE, FLOATUNION_t) + terminator")
    fig.tight_layout(); fig.savefig(os.path.join(args.out, "packet_anatomy.png"), dpi=130)
    print(f"plots written to {args.out}/")
    return 0 if summary["float_mismatches"] == 0 and received > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
