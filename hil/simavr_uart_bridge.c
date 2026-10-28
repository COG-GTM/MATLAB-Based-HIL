// Runs an AVR ELF (arduino:avr:uno build) in simavr, bridges UART0 to a PTY
// (/tmp/simavr-uart0) and throttles the core to wall-clock real time.
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "sim_avr.h"
#include "sim_elf.h"
#include "parts/uart_pty.h"

static double now(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec * 1e-9;
}

int main(int argc, char **argv) {
    if (argc < 2) { fprintf(stderr, "usage: %s firmware.elf\n", argv[0]); return 1; }
    elf_firmware_t fw = {0};
    if (elf_read_firmware(argv[1], &fw)) { fprintf(stderr, "cannot read %s\n", argv[1]); return 1; }
    avr_t *avr = avr_make_mcu_by_name("atmega328p");
    if (!avr) return 1;
    avr_init(avr);
    avr->frequency = 16000000;
    avr_load_firmware(avr, &fw);

    uart_pty_t pty;
    uart_pty_init(avr, &pty);
    uart_pty_connect(&pty, '0');
    fflush(stdout);

    double t0 = now();
    const avr_cycle_count_t slice = 1600; // 100 us
    avr_cycle_count_t next = slice;
    for (;;) {
        int st = avr_run(avr);
        if (st == cpu_Done || st == cpu_Crashed) break;
        if (avr->cycle >= next) {
            next += slice;
            double lag = (double)avr->cycle / avr->frequency - (now() - t0);
            if (lag > 0) {
                struct timespec d = {0, (long)(lag * 1e9)};
                nanosleep(&d, NULL);
            }
        }
    }
    uart_pty_stop(&pty);
    return 0;
}
