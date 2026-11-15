# How it works

## The hardware

The K630 has essentially one chip: a **SinoWealth SH68F90A** microcontroller. Everything else
is switches, LEDs and wiring.

| Part | What it is | Why it matters |
|---|---|---|
| CPU | 8051-compatible core (single-cycle) | An old, well-known architecture: the free compiler SDCC targets it, and uCsim simulates it. |
| Program memory | 64 KB flash | Rewritable, so the keyboard's program is not fixed. |
| Bootloader | 4 KB at the top of flash (`0xF000`), from the factory | Runs on every power-up and accepts new firmware over USB (the vendor's update path). This project only ever writes the 60 KB below it, so it cannot be damaged: there is always a way back. |
| RAM | 256 bytes internal + 4 KB XRAM | Tiny: the call stack (~220 bytes) is analysed statically. |
| USB | full-speed USB device, built in | The firmware talks to the computer directly. |
| Pins + PWM | ~50 pins, 21 PWM channels | Switches and LEDs connect straight to the chip, with no driver chips. |
| Watchdog | resets the chip if the firmware stops checking in | A hung firmware recovers by itself. |

**Keys** sit in a grid of 5 rows × 14 columns. To scan, the chip pulls one column low at a
time and reads which rows go low: those keys are down. **LEDs** sit in a second grid,
6 rows × 21 columns: a row is switched on by pulling it low, and each column has its own PWM
channel that sets the brightness.

What made a custom firmware practical:

1. The bootloader's USB update protocol is supported by
   [sinowisp](https://github.com/karstx/sinowisp), which also read out the stock firmware
   for a backup.
2. [smk](https://github.com/karstx/smk) already supported the SH68F90A on the Eyooso Z11,
   which uses the same reference design as the K630 (the same key-matrix pins).
3. The stock firmware's machine code was read with a small disassembler (`re/dis8051.py`)
   to confirm the K630's wiring: FN keys, the LED grid, the side Caps Lock LED, the clock
   setup ([`re/K630-HARDWARE.md`](../re/K630-HARDWARE.md)).
4. uCsim has a model of this chip (patched by smk), so every image runs on a simulated
   keyboard before it reaches the real one.

## The firmware

```
 power-up
    │
    ▼
 factory bootloader ──(flash command / FN1 / failed start)──► update mode (sinowisp)
    │ jumps to the firmware
    ▼
 early boot: last start failed? FN1 held? ──yes──► update mode
    │ no: mark "starting", start the clock (PLL), USB, timers
    ▼
 ┌──────────── main loop (kicks the watchdog every pass) ─────────────┐
 │  key events from the input queue → Fn layers already applied       │
 │  → keyd engine → output queue → USB reports                        │
 │  keyd timeouts fire at their deadline (overloadt2, oneshot)        │
 │  after 50,000 healthy passes: clear the "starting" mark            │
 └────────────────────────────────────────────────────────────────────┘
        ▲ key events                              USB interrupt: answers the computer,
        │                                         counts 1 ms clock ticks (USB SOF)
 timer interrupt, alternating:
   • key scan:  LED rows off → each column low → read rows → changed keys → Fn → queue
   • LED step:  one LED row on (6 rows in turn), brightness via PWM
```

### 1. Start-up and the safety nets

The factory bootloader runs first and jumps to the firmware. The firmware's first code
(`board_early_boot` in `firmware/redragon-k630/kb.c`), before clocks or USB, does this:

- If a **"starting" marker** (4 bytes at the top of XRAM) is still set, the previous start
  never got healthy: it hung and the watchdog reset it. The firmware then goes to update
  mode instead of hanging again. Otherwise it sets the marker. The main loop clears it
  after 50,000 passes, and so does the flash command just before it hands over to the
  bootloader.
- If **FN1 is held**, it goes to update mode.
- Waiting for the clock (PLL) to lock has a time limit. A clock that never locks also ends
  in update mode rather than a hang.

Every exit to update mode starts the clocks first, because the bootloader's USB needs them.
This was learned on the real keyboard: an early version reached update mode with no USB.

### 2. Key scan

A timer interrupt alternates between a **key scan** and an **LED step** (400 µs).

The scan turns the LED rows off and takes the column pins back from the PWM. It then pulls
each of the 14 columns low in turn and reads the 5 rows twice, 10 µs apart. A key counts
only when both reads agree.

Changed keys go through the **Fn layers** (`kb.c`) first: FN1 and FN2 never reach the keyd
engine. The firmware remembers what each key was pressed *as*, so releasing FN before the
key can't leave a key stuck. Each event is queued with its time in milliseconds.

### 3. The keyd engine

`engine/kd.c` is a port of keyd v2.6.0's `keyboard.c`, kept close to the original so the
two can be read side by side. Your config is not parsed on the keyboard. At build time
`tools/keyd-oracle/export.c` runs keyd's own parser over it and writes C tables
(`kd_config_gen.c`) that are compiled into the image. The keyboard therefore interprets
the config exactly as the keyd daemon does.

Changes needed for the 8051:

- keyd's recursion is replaced by an explicit frame stack in XRAM;
- single-use locals are static, to keep them off the 220-byte stack;
- time comparisons are safe across wrap-around;
- queue overflows drop events (counted) instead of asserting.

Time comes from the USB start-of-frame packets the computer sends every millisecond, so a
175 ms timeout in the config is 175 real milliseconds. The main loop feeds queued events to
the engine in order. Each event first fires any timeouts due before its own time, as keyd
does with real timestamps.

### 4. USB

The engine's output becomes HID reports:

- a 6-key boot keyboard report (endpoint 1),
- an NKRO report and a media-key report (endpoint 2).

The keyboard keeps the stock USB ID `258a:002a`. It answers the same "jump to bootloader"
feature report as the stock firmware, so `sinowisp` flashes it the same way. When the host
suspends the bus, a keypress sends USB remote wakeup, if the host enabled it.

### 5. Backlight

Between key scans, one LED row is on at a time. The six rows cycle fast enough to look
steady. All 21 columns run PWM at about 20 kHz: a period of 300 counts, 50 µs. Each
brightness level sets how much of the period the column is driven: 5, 13, 27, 50 or 97 %.
Eight whole PWM periods fit exactly into each 400 µs LED step, so the brightness does not
depend on where the PWM counter happens to be when the row switches on.

As in the stock firmware, the PWM counters are never stopped: during a key scan only the
pin outputs are switched off. Caps Lock inverts the Caps Lock key's column on its row. The
side Caps Lock LED (P0.3, active low) is held off.

### 6. What is checked before every flash

- **No flash writes**: `tests/firmware/check_no_flash_write.py` scans every byte offset of
  the image for an instruction that writes the flash controller's program/erase registers.
  The firmware cannot erase itself or the bootloader. The stock firmware fails this check,
  because it saves settings, so the check is known to work.
- **Stack**: `tests/firmware/stack_bound.py` follows every call path in the compiled image,
  plus the deepest interrupt arriving at the worst moment. The worst case is 173 of ~222
  bytes. The simulator also measures the peak.
- **Simulator tests** (`tests/firmware/test_k630.py`): the real image runs in uCsim through
  boot, the marker and watchdog fallback, FN1 escape, PLL timeout, USB identity, the flash
  command, Fn layers, backlight, wakeup, and resources.
- **Behaviour vs keyd** (`tests/firmware/sim_difftest.py`): 1001 random key scripts run
  through the image in the simulator and through keyd itself. The outputs must be
  identical.
- **Flashing** (`tools/flash.sh`): AC power, image hash, no flash writes, and a positive
  identification of the connected keyboard.
