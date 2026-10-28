#!/usr/bin/env bash
# Software HIL: build sketches for arduino:avr:uno, run the real firmware in
# simavr (UART0 -> PTY, real-time), drive it from the Simulink stand-in.
# BASELINE_REF=main also runs the unmodified sketch from that ref for before/after.
set -euo pipefail
cd "$(dirname "$0")/.."
OUT=hil/out; BUILD=hil/build; mkdir -p "$OUT" "$BUILD"
PORT=/tmp/simavr-uart0

gcc -O2 -I/usr/include/simavr -I/usr/include/simavr/avr -o "$BUILD/simavr_uart_bridge" \
    hil/simavr_uart_bridge.c -lsimavrparts -lsimavr -lelf -lpthread -lutil

build() { # <sketch dir> <name>
  arduino-cli compile --fqbn arduino:avr:uno --output-dir "$BUILD/$2" "$1" | tee "$OUT/size_$2.txt"
}

run() { # <name> <args...>
  local elf; elf=$(ls "$BUILD/$1"/*.ino.elf); shift
  "$BUILD/simavr_uart_bridge" "$elf" >/dev/null 2>&1 & local pid=$!
  for _ in $(seq 50); do [ -e "$PORT" ] && break; sleep 0.1; done; sleep 0.5
  python3 hil/simulink_standin.py --port "$PORT" "$@"
  kill $pid; wait $pid 2>/dev/null || true; rm -f "$PORT"
}

probe_single() { # single_float_send_receive with an idle host: what does the target emit?
  local elf; elf=$(ls "$BUILD/single"/*.ino.elf)
  "$BUILD/simavr_uart_bridge" "$elf" >/dev/null 2>&1 & local pid=$!
  for _ in $(seq 50); do [ -e "$PORT" ] && break; sleep 0.1; done; sleep 0.5
  python3 - "$PORT" "$OUT/single_idle.json" <<'PY'
import json, math, serial, struct, sys, time
s = serial.Serial(sys.argv[1], 115200, timeout=1.0); s.reset_input_buffer(); d = s.read(6 * 20)
fr = [struct.unpack("<f", d[i + 1:i + 5])[0] for i in range(len(d) - 5) if d[i:i + 1] == b"A" and d[i + 5:i + 6] == b"\n"]
nan = sum(math.isnan(x) for x in fr)
json.dump({"frames": len(fr), "nan": nan, "first_bytes": d[:12].hex()}, open(sys.argv[2], "w"))
print(f"[single_float idle] frames={len(fr)} NaN={nan} raw={d[:12].hex()}")
PY
  kill $pid; wait $pid 2>/dev/null || true; rm -f "$PORT"
}

build single_float_send_receive single
probe_single
build multiple_send_receive after
if [ -n "${BASELINE_REF:-}" ]; then
  mkdir -p "$BUILD/src_before/multiple_send_receive"
  git show "$BASELINE_REF:multiple_send_receive/multiple_send_receive.ino" \
    > "$BUILD/src_before/multiple_send_receive/multiple_send_receive.ino"
  build "$BUILD/src_before/multiple_send_receive" before
  run before --label before --out "$OUT/before_clean.json"
  run before --label before --faults --out "$OUT/before_faults.json"
fi
run after --label after --out "$OUT/after_clean.json"
run after --label after --faults --out "$OUT/after_faults.json"
python3 hil/plot_hil.py "$OUT"
