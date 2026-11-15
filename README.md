# K630 keyd firmware

Custom firmware for the **Redragon K630** (60%, single-colour backlight) that runs a
[keyd](https://github.com/rvaiya/keyd) config **inside the keyboard**. Your layout, home-row
style tap/hold layers, oneshot modifiers and layout switching then work on any computer,
with nothing installed on it.

The firmware is built on [smk](https://github.com/karstx/smk) (open firmware for SinoWealth
keyboards) and contains a port of keyd v2.6.0's own key engine. Your config is compiled with
keyd's own parser, and every image is checked against keyd itself in a simulator before it
can be flashed.

> **Warning.** Flashing custom firmware is at your own risk and may void your warranty.
> The project is designed to make bricking very unlikely and to leave several ways back
> (see [Safety](#safety)), but it cannot rule it out, and it has been built and tested on
> **one** keyboard. Read this whole page before flashing.

## What you get

- **Your keyd config on the keyboard**: everything keyd's `[main]`/layer syntax offers for
  keys: plain remaps and modifier combos, `layer`, `oneshot`, `toggle`, `overload`,
  `overloadt`, `overloadt2`, `setlayout`/layouts, `clear`. Timeouts are real milliseconds
  (from the USB clock). Not supported: macros, commands, chords, composite layers, `swap`,
  `timeout()`; the build refuses configs that use them.
- **Fn layers as on the stock keyboard**, applied before the keyd engine:
  - FN1 + Esc → `` ` ``, 1…= → F1…F12, W A S D → arrows, P → PrtSc, [ ] → Home/End,
    ; ' → PgUp/PgDn, . → Ins, / → Del, FN1 + Win → Win lock.
  - FN2 tapped → Menu. FN2 + 0 → backlight on/off, FN2 + − / = → dimmer / brighter.
- **Backlight**: one mode, all keys at one brightness (5 steps), off by default.
  **Caps Lock** is shown on the Caps Lock key itself: lit when the backlight is off, dark when
  it is on. Settings are not saved: the firmware never writes to flash.
- **Wakes the computer** from sleep on a keypress.
- Same USB ID as the stock keyboard (`258a:002a`), so OS settings keep working.

## Supported hardware

Only the **Redragon K630 single-colour** (the "norgb" model, e.g. the pink one) with:

| | |
|---|---|
| USB ID | `258a:002a` (stock firmware), `0603:1020` in update mode |
| Stock firmware version | bcdDevice **12.10** |
| Microcontroller | SinoWealth SH68F90A |

The RGB, wireless and other K630 variants are **not** supported unless verified.
`tools/flash.sh` refuses to flash anything it cannot positively identify as this keyboard,
and refuses a stock keyboard until you have backed up its firmware and that backup matches
the known 12.10 image.

## Quick start

Linux only (developed on Arch). You need git, Python 3, a C compiler, Rust (for sinowisp),
and the packages `meson ninja boost bison flex`.

```sh
git clone <this repo> && cd <this repo>
tools/setup.sh                 # builds SDCC 4.5.0, the patched simulator, sinowisp; applies firmware/smk.patch
```

1. **Back up your keyboard's stock firmware** (it is not in this repo). See
   [`backup/README.md`](backup/README.md). This is also how you get back to stock later.
2. **Put your keyd config** in `keymap/` (`keymap/rynsf.conf` is the author's: Colemak with
   angle mod, tap/hold symbol layers, oneshot shift). Build with `CONFIG=keymap/yours.conf`,
   or edit `CONFIG` in the `Makefile`.
3. **Build and test** (nothing touches the keyboard):
   ```sh
   make test-firmware
   ```
   It must end in `OK` and `firmware vs keyd: 1001/1001 identical`.
4. **Flash** (on mains power):
   ```sh
   sha256sum build/smk/redragon-k630_default_smk.hex
   tools/flash.sh build/smk/redragon-k630_default_smk.hex <sha256>
   ```

Changing the layout later, and recovery, are covered in
[`docs/CHANGING-LAYOUT.md`](docs/CHANGING-LAYOUT.md).

If you also run keyd on the computer, exclude the keyboard from it, or every key is
remapped twice:

```ini
[ids]
*
-258a:002a
```

## Safety

The SH68F90A has a factory bootloader in the top 4 KB of flash that accepts new firmware
over USB. It runs on every power-up and is never written by this project. sinowisp marks
the firmware valid only as its last step, so an interrupted flash leaves the bootloader in
update mode, ready to try again. On top of that, every image has to:

- **never write flash**: `tests/firmware/check_no_flash_write.py` proves that no byte of
  the image encodes a write to the flash controller (the stock firmware fails this check,
  since it saves settings);
- keep **three ways into update mode**: the flash command `sinowisp` uses, holding **FN1**
  while plugging in, and an automatic fallback when a start hangs (a watchdog reset during
  startup leads to update mode instead of another hang);
- pass the **simulator tests**: the real image runs in uCsim's SH68F90 model through boot,
  the escape hatches, USB, the Fn layers, the backlight, wakeup, worst-case stack use
  (statically bounded), and 1001 random key scripts compared against keyd.

**What is not covered.** The three ways into update mode are the firmware's own code. An
image broken so badly that it fails before its first instructions run (where the FN1
check is) would leave only in-circuit programming: opening the keyboard and writing the
chip directly with [sinodude](https://github.com/karstx/sinodude) and an Arduino Nano.
The simulator boots every image before it can be flashed, precisely to catch that, but
that last-resort path has not been tested on this keyboard.

[`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md) explains the hardware and the firmware in
detail. [`re/K630-HARDWARE.md`](re/K630-HARDWARE.md) is the hardware map recovered from the
stock firmware. [`docs/DESIGN.md`](docs/DESIGN.md) is the project log, including every flash.

## Repository layout

| Path | Contents |
|---|---|
| `firmware/redragon-k630/` | the K630 board for smk: pins, matrix, Fn layers, backlight, boot safety, USB glue |
| `firmware/smk.patch` | small changes to smk's core (board hooks, USB ms clock, remote wakeup) |
| `firmware/known-good.hex` | the image currently in use by the author (fallback) |
| `engine/` | `kd`: keyd v2.6.0's key engine ported to the 8051 |
| `tools/keyd-oracle/` | keyd's parser as a config compiler (`keyd-export`) and a reference runner |
| `tools/` | `setup.sh` (toolchain), `flash.sh` (guarded flashing) |
| `tests/` | host difftests vs keyd; `tests/firmware/` simulator tests |
| `keymap/` | keyd configs |
| `re/` | reverse-engineering notes and tools for the stock firmware |

## Credits

- [smk](https://github.com/karstx/smk) and [sinowisp](https://github.com/karstx/sinowisp)
  by Karolis Stasaitis: the firmware base, the patched uCsim model, and the ISP flasher.
- [keyd](https://github.com/rvaiya/keyd) by Raheman Vaiya: the engine and parser.
- [SDCC](https://sdcc.sourceforge.net/) and uCsim.

## License

GPL-2.0, the same as smk, on which the firmware is built (see `LICENSE`). `engine/` is a
port of keyd and keeps keyd's MIT license (`engine/LICENSE.keyd`).
Redragon's firmware, manuals and product images are not part of this repository.
