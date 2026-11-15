# Design notes

Goal: a keyd config (keyd v2.6.0) running inside the Redragon K630, behaving exactly as the
keyd daemon does, without risking the keyboard. How the pieces work is described in
[`HOW-IT-WORKS.md`](HOW-IT-WORKS.md); this page records the rules the project follows, the
design decisions and what was verified on the real keyboard.

Base: [smk](https://github.com/karstx/smk), firmware for SinoWealth 8051 keyboards. It
already supported the SH68F90A (on the Eyooso Z11, same reference design as the K630): USB
stack, matrix scan, watchdog, ISP jump, and a uCsim model of the chip.

## Ground rules (anti-brick)

1. **Nothing is flashed until it has passed in the simulator**: boot, USB enumeration, the
   ISP-jump command, the escape hatches below, and the keymap behaviour against keyd.
2. **The stock bootloader is never touched.** Only the firmware area is written, with
   `sinowisp write` over ISP. No code-option writes. No flash writes from the firmware:
   settings use a no-op `nvm` module, `flash.c` is not linked into release images, and
   `tests/firmware/check_no_flash_write.py` proves that no byte offset of the image encodes
   a write to the flash controller's program/erase registers (IB_CON2/3).
3. **Every build keeps these ways back into ISP mode:**
   - *ISP command*: the firmware enumerates as `258a:002a` and handles feature report 5 /
     `0x75`, so `sinowisp -d redragon-k630-norgb` keeps working.
   - *Boot escape*: holding **FN1** while plugging in jumps to the bootloader. It runs first
     in `init()`, before clocks, USB or anything else.
   - *Watchdog fallback*: the watchdog is only kicked from a healthy main loop. The stock
     bootloader clears `RSTSTAT` before jumping to the firmware, so the reset cause is
     lost; instead a 4-byte marker at the top of XRAM (`0x0FFC`, above all linker data) is
     set to BOOTING at start and cleared after 50,000 healthy main-loop passes, and just
     before the ISP command's jump. A start that finds BOOTING followed a hang during boot,
     so it jumps to ISP.
   - *Bounded PLL wait*: a PLL that never locks ends in ISP instead of a hang.
   - Every early ISP exit starts the LDO and PLL first: the bootloader's ISP entry needs a
     running clock for USB.
4. **Before flashing**: simulator tests green, image below `0xEFFB`, a verified backup of
   the stock firmware (`backup/`), mains power, a stable USB link, and the keyboard running
   for a minute (so it is past its start-up window). `tools/flash.sh` enforces what it can.
5. **The first flash was a canary**: plain keys (pass-through config) plus the escape
   hatches, followed by a round trip to stock and back, before any feature build.
6. **Last resort**: in-circuit programming with
   [sinodude](https://github.com/karstx/sinodude) needs an Arduino Nano (5 V) or a SinoLink;
   a Raspberry Pi Pico does not work out of the box. Not built or tested here.

## Design decisions

- **Fn layers before the keyd engine.** keyd never sees Fn on a stock keyboard, so the
  firmware applies the stock Fn layer first (FN1 + W enters the engine as `up`). This keeps
  the pipeline identical to "stock keyboard + keyd on the computer". Each key remembers what
  it was pressed as, so releasing Fn first cannot leave a key stuck.
- **The config is compiled with keyd's own parser** (`tools/keyd-oracle/export.c`), which
  refuses anything the engine does not implement, rather than reimplementing keyd's syntax.
- **Clock**: keyd's timeouts use the USB start-of-frame counter (exactly 1 ms). The
  SH68F90 has no free timer for it. The clock stops while the host suspends the bus.
- **Stack**: the 8051's ~220-byte internal stack is shared with the interrupts. The engine
  runs from the main loop through two small XRAM queues (keys in, outputs out), never inside
  smk's key handler; it has no recursion (overload taps replay in a loop; keyd's recursive
  flush is an explicit frame stack in XRAM), and single-use locals are static.
  `tests/firmware/stack_bound.py` proves the worst case over every call path from the
  image's assembly: main loop 100 + USB ISR 73 = 173 of 222 bytes (the interrupts share one
  priority, so they cannot nest). The test fails below 32 bytes spare.
- **Backlight**: one mode, all keys at one brightness, off at power-up, 5 levels, nothing
  saved. The stock firmware drives a 6 × 21 LED grid (rows P6.0–5, active low; columns =
  the 14 key-column PWM channels plus PWM20–23 and PWM40–42); the firmware drives the same
  grid. As in the stock firmware, the PWM counters never stop: for the key scan only the
  pin outputs are released and the LED rows switched off. The PWM period (300 counts) fits
  the 400 µs LED step 8 times, so brightness does not depend on the counter's phase. Caps
  Lock is shown on its own key as the inverse of the backlight; the side Caps LED (P0.3,
  active low) is held off. Dark while suspended.
- **Remote wakeup**: a key press while the host has the bus suspended sets USBCON.WKUP once
  (if the host enabled remote wakeup), as the stock firmware does; that press is dropped.
- **Media keys** share the one-usage consumer report (as in the stock descriptor): a
  release only clears the report if it is the key being reported.
- **No PWM interrupt**: smk's PWM handler is empty and never clears its flag; with the
  short PWM period it would re-enter back to back.

## Tests

`make test-firmware` runs on the image itself, in uCsim:

- boot, marker set and cleared; ISP command during the start-up window clears it first
- watchdog: a hang → watchdog reset → ISP, end to end; restart with a stale marker → ISP
- FN1 at power-up → ISP; no key → normal boot; PLL that never locks → ISP
- USB ID `258a:002a`; ISP report → bootloader (a wrong confirm does not jump)
- every FN1 translation, Fn released first, FN2 tap/combo, Win-lock
- backlight state, combos, Caps Lock duties, LED rows off and PWM running during scans,
  PWM period, column pins returned to the scan, side LED off; no PWM interrupt
- remote wakeup
- stack: static worst-case bound over all paths, plus measured peaks below it
- no flash-write encoding; XRAM below the marker; image below `0xEFFB`
- the image against keyd itself: scripted, scenario and 1000 random sequences

`make test` runs the engine on the host against keyd (no simulator).

Harness notes: `sim_difftest.py` runs several simulators side by side (`--jobs`, default
`nproc`); each script gets a fresh boot. Replaying a long script through the pin-level
matrix scan (`--pins`) can stall uCsim's command socket (the simulator sits idle waiting
for a command; a firmware hang would show 100% CPU), so the default runs drive `matrix[]`
directly. The pin-level path is covered by `test_k630` and by earlier pin-level runs that
matched keyd.

## Verified on the real keyboard

| Milestone | Result |
|---|---|
| Canary (pass-through) flash | Ran; the FN1 boot escape reached ISP mode **without USB**: the bootloader's ISP entry does not start the PLL. Fixed (clocks first), simulator test added, verified on hardware. |
| Round trip | Stock → canary → stock → canary via the ISP command; the stock restore verified by read-back. |
| Full keyd image | Behaves as keyd on the computer did. |
| Remote wakeup | Wakes the computer from sleep. |
| Backlight, first version (smk's Z11 PWM setup) | Brightness barely changed: most columns were never under PWM. Replaced by the stock setup. |
| Side Caps LED | Glowed while P0.3 floated; driven high now. |
| Caps Lock with backlight off | Lit the whole board: the last LED row stayed on during key scans. Fixed (rows off before each scan, PWM never stopped); brightness steps now visible. |
| Flash sent shortly after a replug | The new image's first start went to ISP: the ISP command jumped without clearing the boot marker. Fixed (`board_before_isp`), simulator test added. |
| Key 4's LED dark | Dark on the stock firmware too: a hardware fault on the test keyboard, not firmware. |
