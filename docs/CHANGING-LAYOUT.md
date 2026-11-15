# Changing the K630 layout

The keyboard runs your keyd config itself: `keymap/rynsf.conf` is compiled into the firmware
with keyd v2.6.0's own parser. To change the layout you edit that file, rebuild, test in the
simulator, and flash. Nothing reaches the keyboard until the last step.

## 1. Edit the config

- **`keymap/rynsf.conf`** (and `keymap/layouts/colemak`, which it includes) is the source.
  If keyd also runs on the computer, keep its config in step with this one.
- Write it exactly as for keyd. Key names are what the keyboard sends before any
  remapping, i.e. the QWERTY legends.
- **Supported:** plain keys and modifier combos, `layer`, `oneshot`, `toggle`, `setlayout`,
  `clear`, `overload`, `overloadt`, `overloadt2`, and layouts, up to 32 layers.
- **Not supported** (the build stops with `keyd-export: unsupported by the firmware engine`):
  macros, commands, chords, composite layers (`[a+b]`), and other actions such as `swap`,
  `timeout`, `oneshotm`/`layerm`.
- `[ids]` is ignored by the firmware (the `-258a:002a` line is only for the keyd daemon).

**FN1 / FN2 are not in the keyd config.** They live in the firmware, before the keyd engine,
in `firmware/redragon-k630/kb.c` (the FN1 table: Esc → `` ` ``, 1…= → F1…F12, WASD →
arrows, P → PrtSc, [ ] → Home/End, ; ' → PgUp/PgDn, . → Ins, / → Del; FN2: tap = Menu,
FN2 + 0 / − / = = backlight on-off / dimmer / brighter).

## 2. Build and test (nothing touches the keyboard)

```sh
make test-firmware
```

This builds the image and then:

- runs the simulator tests (boot, escape hatches, Fn layers, backlight, wakeup, stack,
  no flash writes), which must end in `OK`;
- replays 1001 key scripts through both the firmware (in the simulator) and keyd itself,
  which must end in `firmware vs keyd: 1001/1001 identical`.

If either fails, do not flash. `make test` checks the config against keyd on the host alone (no
simulator), which is quicker while editing.

## 3. Flash

On mains power (a laptop: charger plugged in), with the keyboard connected and in normal use for at
least a minute (so the new firmware's first start is a clean one). Then:

```sh
sha256sum build/smk/redragon-k630_default_smk.hex
tools/flash.sh build/smk/redragon-k630_default_smk.hex <the sha256 printed above>
```

`tools/flash.sh` refuses unless the computer is on mains power, the image matches that hash, the
image contains no flash-write code, and the keyboard is present. It then writes with
`sinowisp` and verifies. On battery (at least 50%), prefix it with `K630_ALLOW_BATTERY=1`.
The keyboard reconnects as "SMK Keyboard" a few seconds later.

Add a line to the flash log in `docs/DESIGN.md`. Once the new image has proved itself in use, keep
it as the fallback and commit:

```sh
cp build/smk/redragon-k630_default_smk.hex firmware/known-good.hex
```

## If something goes wrong

- **The keyboard comes back as `0603:1020` ("Gaming KB", update mode):** not bricked. Unplug
  it, wait 3 s, plug it back in without touching any keys. If it stays in update mode, flash
  the last good image, `firmware/known-good.hex` (`sha256sum` it and use `tools/flash.sh` as
  above; it works from update mode too).
- **The new layout misbehaves:** flash `firmware/known-good.hex` the same way.
- **The keyboard does not respond at all:** hold **FN1** while plugging it in. That starts
  the bootloader (update mode), so you can flash `firmware/known-good.hex`.
- **Back to the factory firmware:**
  `PATH=$PWD/tools/bin:$PATH sinowisp write -d redragon-k630-norgb -f backup/k630-stock-firmware.hex`
  (it types plain QWERTY again; its update command works too, so our firmware can go back on).

## First time on a new machine

`tools/setup.sh` builds the toolchain (SDCC 4.5.0, the patched simulator, sinowisp) and
applies `firmware/smk.patch` to smk. It needs the Arch packages `meson ninja boost bison
flex`.
