/*
 * kd: a port of keyd v2.6.0's key-processing core (src/keyboard.c) for the SH68F90 (SDCC) and
 * for the host (differential tests against keyd itself).
 *
 * Codes are keyd keycodes (Linux evdev numbering, keys.h). Time is in ms.
 */
#ifndef KD_H
#define KD_H

#include <stdint.h>

typedef int32_t kd_time_t;

/* Provided by the platform: one key event leaves the engine. */
void kd_output(uint8_t code, uint8_t pressed);

void kd_init(void);

/*
 * Feed one key event (code != 0) or a timeout tick (code == 0) at time `t`.
 * Returns how many ms from `t` the next timeout tick is due, or 0 if none is pending.
 * This is exactly the daemon's use of kbd_process_events(kbd, &ev, 1).
 */
kd_time_t kd_event(uint8_t code, uint8_t pressed, kd_time_t t);

/* Counters for conditions keyd would assert on; non-zero means input was dropped. */
extern uint8_t kd_overflow;
/* Deepest nesting of overload flushes seen (1 = none). */
extern uint8_t kd_peak_frames;

#endif
