#!/usr/bin/env python3
"""Simulink stand-in for multiple_send_receive: streams 'x'+3*float32+'\n' frames
at 50 ms, parses 'A'+3*float32+'\n' replies, optionally injects UART faults."""
import argparse, json, math, struct, threading, time
import serial

PERIOD = 0.05
RX_LEN = 14

# packet index -> fault kind
FAULTS = {
    30: "noise burst with 'x'",
    60: "split packet (25 ms gap)",
    90: "wrong header",
    120: "missing terminator",
    150: "truncated payload",
    170: "stray byte mid-payload",
}


def values(k):
    return (float(k), round(10 * math.sin(2 * math.pi * k / 40), 3), round(5 * math.cos(2 * math.pi * k / 40), 3))


def frame(k):
    return b"x" + struct.pack("<3f", *values(k)) + b"\n"


def send(ser, k, fault):
    f = frame(k)
    if fault is None:
        ser.write(f)
    elif fault.startswith("noise"):
        ser.write(b"x\x13\x37" + f)
    elif fault.startswith("split"):
        ser.write(f[:7]); ser.flush(); time.sleep(0.025); ser.write(f[7:])
    elif fault.startswith("wrong"):
        ser.write(b"X" + f[1:])
    elif fault.startswith("missing"):
        ser.write(f[:-1])
    elif fault.startswith("truncated"):
        ser.write(f[:6] + f[7:])
    elif fault.startswith("stray"):
        ser.write(f[:7] + b"\x55" + f[7:])
    ser.flush()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/tmp/simavr-uart0")
    ap.add_argument("--packets", type=int, default=200)
    ap.add_argument("--faults", action="store_true")
    ap.add_argument("--label", default="run")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    ser = serial.Serial(a.port, 115200, timeout=0.01)
    time.sleep(0.3)
    ser.reset_input_buffer()
    rx, bad_bytes, stop = [], [0], threading.Event()

    def reader():
        buf = b""
        while not stop.is_set():
            buf += ser.read(max(1, ser.in_waiting))
            t = time.monotonic()
            while len(buf) >= RX_LEN:
                if buf[0:1] == b"A" and buf[RX_LEN - 1:RX_LEN] == b"\n":
                    rx.append((t, struct.unpack("<3f", buf[1:13])))
                    buf = buf[RX_LEN:]
                else:
                    buf = buf[1:]; bad_bytes[0] += 1

    th = threading.Thread(target=reader, daemon=True); th.start()
    tx = {}
    t0 = time.monotonic()
    for k in range(1, a.packets + 1):
        target = t0 + k * PERIOD
        while time.monotonic() < target:
            time.sleep(0.0005)
        fault = FAULTS.get(k) if a.faults else None
        tx[k] = (time.monotonic(), fault)
        send(ser, k, fault)
    time.sleep(0.3)
    stop.set(); th.join()
    t_end = time.monotonic()

    sent = {k: values(k) for k in tx}
    first_seen, phantoms, timeline = {}, [], []
    for t, v in rx:
        v = tuple(v)
        k = int(v[0]) if v[0] == v[0] and abs(v[0]) < 1e6 and v[0] == int(v[0]) else None
        ok = k in sent and all(abs(x - y) < 1e-3 for x, y in zip(v, sent[k]))
        if ok:
            first_seen.setdefault(k, t)
        elif any(abs(x) > 1e-12 for x in v) or rx and t > t0 + 0.2:
            if not (v == (0.0, 0.0, 0.0) and not first_seen):
                phantoms.append({"t": t - t0, "v": [x if x == x and abs(x) < 1e30 else None for x in v]})
        timeline.append({"t": t - t0, "v": [x if x == x and abs(x) < 1e30 else None for x in v], "ok": ok, "k": k if ok else None})

    rtt = {k: (first_seen[k] - tx[k][0]) * 1000 for k in first_seen}
    lost = [k for k in tx if k not in first_seen]
    fault_ks = {k for k, (_, f) in tx.items() if f}
    # Loss attribution between consecutive echoed packets p < n. Host and target run free 50 ms loops, so the
    # RTT ramps with clock drift and wraps back to the transport floor. Near the wrap two host packets can land in
    # one target loop and the older is overwritten: "superseded", not a fault. Any other non-fault loss is collateral.
    lost_fault = [k for k in lost if k in fault_ks]
    lost_superseded, lost_collateral = [], []
    seen = sorted(first_seen)
    floor = min(rtt.values()) if rtt else 0
    for i, (p, n) in enumerate(zip(seen, seen[1:])):
        others = [k for k in range(p + 1, n) if k not in fault_ks]
        if not others:
            continue
        before = [rtt[q] for q in seen[max(0, i - 3):i + 1] if rtt[q] <= PERIOD * 1000 + 10]
        wrapped = bool(before) and min(before) - rtt[n] > PERIOD * 1000 / 2
        at_wrap = rtt[n] <= floor + 3
        (lost_superseded if wrapped or at_wrap else lost_collateral).extend(others)
    fault_rows = []
    for k, (t_tx, f) in tx.items():
        if not f:
            continue
        nxt = [kk for kk in range(k + 1, k + 20) if kk in first_seen]
        win = [p for p in phantoms if t_tx - t0 <= p["t"] <= t_tx - t0 + 1.0]
        fault_rows.append({
            "k": k, "fault": f, "t": t_tx - t0,
            "faulty_packet_echoed": k in first_seen,
            "corrupt_frames_committed": len(win),
            "good_packets_lost_after": len([kk for kk in lost_collateral if k < kk <= k + 3]),
            "recovery_ms": round((first_seen[nxt[0]] - t_tx) * 1000, 1) if nxt else None,
        })
    dur = t_end - t0
    res = {
        "label": a.label, "faults": a.faults, "packets_sent": len(tx), "frames_received": len(rx),
        "bad_rx_bytes": bad_bytes[0], "phantom_frames": len(phantoms),
        "packets_echoed": len(first_seen), "packets_lost": lost, "lost_faulty_packet": lost_fault,
        "lost_collateral": lost_collateral, "lost_superseded": lost_superseded,
        "rtt_ms": rtt, "rtt_mean": sum(rtt.values()) / max(len(rtt), 1),
        "rtt_p99": sorted(rtt.values())[int(0.99 * (len(rtt) - 1))] if rtt else None,
        "rtt_max": max(rtt.values()) if rtt else None,
        "rx_frames_per_s": len(rx) / dur, "rx_bytes_per_s": len(rx) * RX_LEN / dur,
        "tx_bytes_per_s": len(tx) * 14 / dur,
        "fault_rows": fault_rows, "phantoms": phantoms, "timeline": timeline,
        "tx": {k: [t - t0, f] for k, (t, f) in tx.items()},
    }
    json.dump(res, open(a.out, "w"), indent=1)
    print(f"[{a.label}{' +faults' if a.faults else ''}] sent={len(tx)} rx_frames={len(rx)} echoed={len(first_seen)} "
          f"lost={len(lost)} (collateral={len(lost_collateral)} superseded={len(lost_superseded)}) phantom={len(phantoms)} rtt_mean={res['rtt_mean']:.1f}ms p99={res['rtt_p99']}")
    for r in fault_rows:
        print(f"   pkt {r['k']:3d} {r['fault']:26s} corrupt_committed={r['corrupt_frames_committed']} "
              f"good_lost_after={r['good_packets_lost_after']}")


if __name__ == "__main__":
    main()
