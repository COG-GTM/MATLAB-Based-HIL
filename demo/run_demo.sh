#!/usr/bin/env bash
# Stage 1 demo: Model-Based Design & plant/controller interface.
#  1. Compile both Arduino sketches for the real target (arduino:avr:uno) -> size report
#  2. Compile the UNMODIFIED multiple_send_receive.ino for the host via a tiny Arduino shim
#  3. Create a virtual serial link (socat PTY pair), run the sketch on one end and the
#     Simulink-side Python harness on the other, exchange real 'x'/'A' float packets
#  4. Write logs + PNG plots to demo/out/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/demo/out"
DURATION="${DURATION:-6}"
mkdir -p "$OUT"
export PATH="$PATH:$HOME/.local/bin:$HOME/bin"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

step "1/4  Compile firmware for real target (arduino:avr:uno) with arduino-cli"
if ! command -v arduino-cli >/dev/null; then
  curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | BINDIR="$HOME/.local/bin" sh
fi
arduino-cli core list 2>/dev/null | grep -q '^arduino:avr' || { arduino-cli core update-index; arduino-cli core install arduino:avr; }
: > "$OUT/firmware_build.txt"
for sk in single_float_send_receive multiple_send_receive; do
  echo "--- $sk ($(arduino-cli version | head -1)) ---" | tee -a "$OUT/firmware_build.txt"
  arduino-cli compile --fqbn arduino:avr:uno --output-dir "$OUT/fw_$sk" "$ROOT/$sk" 2>&1 | tee -a "$OUT/firmware_build.txt"
done
ls -l "$OUT"/fw_*/*.hex

step "2/4  Compile the SAME multiple_send_receive.ino for the host (Arduino core shim)"
g++ -std=gnu++17 -O2 -Wall -x c++ -include "$ROOT/demo/host/arduino_shim.h" \
    "$ROOT/multiple_send_receive/multiple_send_receive.ino" -o "$OUT/mcu_sim"
echo "built $OUT/mcu_sim  ($(wc -c < "$OUT/mcu_sim") bytes)"

step "3/4  Virtual UART (socat PTY pair) + run sketch <-> Simulink-side harness"
TTY_SIM="$OUT/ttySIMULINK"; TTY_MCU="$OUT/ttyMCU"
rm -f "$TTY_SIM" "$TTY_MCU"
socat -d -d pty,raw,echo=0,link="$TTY_SIM" pty,raw,echo=0,link="$TTY_MCU" 2>"$OUT/socat.log" &
SOCAT=$!
for _ in $(seq 50); do [ -e "$TTY_SIM" ] && [ -e "$TTY_MCU" ] && break; sleep 0.1; done
trap 'kill $SOCAT ${MCU:-} 2>/dev/null || true' EXIT
MCU_TTY="$TTY_MCU" "$OUT/mcu_sim" 2>"$OUT/mcu_sim.log" &
MCU=$!
sleep 0.3
python3 "$ROOT/demo/host/simulink_host.py" --port "$TTY_SIM" --duration "$DURATION" --out "$OUT" | tee "$OUT/harness.log"
kill $MCU $SOCAT 2>/dev/null || true
cat "$OUT/mcu_sim.log"

step "4/4  Artifacts"
ls -1 "$OUT"/*.png "$OUT"/summary.json "$OUT"/packets.csv "$OUT"/firmware_build.txt
