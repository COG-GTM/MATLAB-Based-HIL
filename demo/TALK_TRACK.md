# Stage 1 — Model-Based Design & plant/controller interface

## Talk track (~140 words)

Everything downstream in this pipeline — code generation, bare-metal firmware, AUTOSAR
integration, virtual HIL, the release gate — talks to the plant through one contract, and
this is where it's defined.

The Simulink model owns the plant. The controller MCU owns the algorithm. Between them:
a 14-byte frame — one header byte, three IEEE-754 floats via a `FLOATUNION_t`, a newline —
at 115200 baud, every 50 milliseconds. That's the whole interface.

Here we build the real Arduino firmware with `arduino-cli`, then run the *same* sketch
source on the host against a virtual UART while a Python harness plays the Simulink side,
streaming a second-order plant response. 120 frames out, 120 frames back, zero float
mismatches, round-trip well inside the 50 ms budget.

Notice the latency ramp: two free-running 50 ms loops beating against each other. That
is exactly why the Simulink Serial Receive block must use the same sample time as the sketch.

## What you're seeing

- `arduino-cli` size report: both sketches compile for ATmega328P (~1.9 KB flash, 208 B RAM).
- Terminal log: `x`-frames sent by the Simulink-side harness, `A`-frames echoed by the sketch, RTT per packet.
- `sent_vs_received.png`: plant setpoint/position/velocity, every sample echoed bit-exact.
- `latency.png`: RTT histogram and drift — the 50 ms cadence contract made visible.
- `packet_anatomy.png`: the byte layout every later stage reuses.

## Hand-off

Next: Stage 2 replaces hand-written firmware with Embedded Coder auto-generated C from the Simulink controller — speaking this exact frame format.
