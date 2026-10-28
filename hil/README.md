# Software HIL for the Simulink serial bridge

Runs the real `arduino:avr:uno` firmware in [simavr](https://github.com/buserror/simavr) (ATmega328P, 16 MHz, throttled to real time),
bridges UART0 to a PTY (`/tmp/simavr-uart0`), and drives it from `simulink_standin.py`, a pyserial stand-in for the
Simulink Serial Send/Receive blocks (`'x'`+3×float32+`'\n'` out, `'A'`+3×float32+`'\n'` back, 115200 baud, 50 ms).
No MATLAB licence or board needed; same firmware image and byte protocol as the bench.

```bash
sudo apt-get install -y simavr libsimavr-dev libelf-dev && pip install pyserial matplotlib
arduino-cli core install arduino:avr
BASELINE_REF=main ./hil/run_hil.sh   # before/after; omit BASELINE_REF to test the working tree only
```

Each run: 200 packets clean, then 200 packets with injected faults (noise burst containing `'x'`, split packet,
wrong header, missing terminator, truncated payload, stray byte). Output in `hil/out/`: per-run JSON,
`hil_latency.png`, `hil_fault_recovery.png`, `hil_scorecard.png`, `report.html`.

`corrupt committed` = a reply frame carrying values the host never sent. `superseded` = two host packets landed in one
50 ms target loop (clock drift), so the older one was overwritten; expected for free-running 50 ms loops.
