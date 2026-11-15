# Changing the K630 layout

The keyboard runs a keyd config itself: the config is compiled into the firmware with keyd
v2.6.0's own parser. To change the layout you edit the config, rebuild, test in the
simulator, and flash. Nothing reaches the keyboard until the last step.

## 1. Edit the config

- Put your config in `keymap/` (e.g. `keymap/mine.conf`). `keymap/rynsf.conf`, the default,
  is the author's (Colemak with angle mod, tap/hold symbol layers, oneshot shift) and a
  working example. `include layouts/colemak` and similar lines resolve to `keymap/layouts/`.
- Write it exactly as for keyd. Key names are what the keyboard sends before any
  remapping, i.e. the QWERTY legends.
- **Supported:** plain keys and modifier combos, `layer`, `oneshot`, `toggle`, `setlayout`,
  `clear`, `overload`, `overloadt`, `overloadt2`, and layouts, up to 32 layers.
- **Not supported** (the build stops with `keyd-export: unsupported by the firmware engine`):
  macros, commands, chords, composite layers (`[a+b]`), and other actions such as `swap`,
  `timeout`, `oneshotm`/`layerm`.
- `[ids]` is ignored by the firmware. If keyd also runs on the computer, exclude the
  keyboard there (`-258a:002a` under `[ids]`), or every key is remapped twice.

**FN1 / FN2 are not in the keyd config.** They live in the firmware, before the keyd engine,
in `firmware/redragon-k630/kb.c` (the FN1 table: Esc → `` ` ``, 1…= → F1…F12, WASD →
arrows, P → PrtSc, [ ] → Home/End, ; ' → PgUp/PgDn, . → Ins, / → Del; FN2: tap = Menu,
FN2 + 0 / − / = = backlight on-off / dimmer / brighter).

## 2. Build and test (nothing touches the keyboard)

```sh
make test-firmware CONFIG=keymap/mine.conf
```

This builds the image and then:

- runs the simulator tests (boot, escape hatches, Fn layers, backlight, wakeup, stack,
  no flash writes), which must end in `OK`;
- replays 1001 key scripts through both the firmware (in the simulator) and keyd itself,
  which must end in `firmware vs keyd: 1001/1001 identical`.

If either fails, do not flash. `make test-config CONFIG=keymap/mine.conf` checks the config
against keyd on the host alone (no simulator), which is quicker while editing.
`tools/bin/keyd-inspect <config>` prints how keyd parsed a config, which helps when a
mapping does not do what you expect.

## 3. Flash

On mains power, with the keyboard connected and in normal use for at least a minute (so it
is past its start-up window and the new firmware's first start is a clean one):

```sh
sha256sum build/smk/redragon-k630_default_smk.hex
tools/flash.sh build/smk/redragon-k630_default_smk.hex <the sha256 printed above>
```

`tools/flash.sh` refuses unless the computer is on mains power, the image matches that
hash, the image contains no flash-write code, and the connected device is this K630:
running this firmware, or running the stock firmware 12.10 *with* a matching backup in
`backup/` (`tools/flash.sh --identify` shows what it sees). It then writes with `sinowisp`
and verifies. On a laptop on battery (at least 50%), prefix it with `K630_ALLOW_BATTERY=1`.
The keyboard reconnects as "SMK Keyboard" a few seconds later.

Once an image has proved itself in use, keep a copy as your fallback, e.g.:

```sh
cp build/smk/redragon-k630_default_smk.hex ~/k630-good.hex
```

(`firmware/known-good.hex` is the author's image, built from `keymap/rynsf.conf`.)

## If something goes wrong

- **The keyboard comes back as `0603:1020` ("Gaming KB", update mode):** not bricked. Unplug
  it, wait 3 s, plug it back in without touching any keys. If it stays in update mode, flash
  your last good image (`sha256sum` it and use `tools/flash.sh` as above, with
  `K630_ISP_MODE_OK=1` in front: in update mode the script cannot tell the K630 from other
  SinoWealth boards, so it asks you to confirm).
- **The new layout misbehaves:** flash your last good image the same way.
- **The keyboard does not respond at all:** hold **FN1** while plugging it in. That starts
  the bootloader (update mode), so you can flash your last good image.
- **Back to the factory firmware:** flash your own backup (see `backup/README.md`):
  `PATH=$PWD/tools/bin:$PATH sinowisp write -d redragon-k630-norgb -f backup/k630-stock-firmware.hex`
  (it types plain QWERTY again; its update command works too, so this firmware can go back on).

## First time on a new machine

`tools/setup.sh` builds the toolchain (SDCC 4.5.0, the patched simulator, sinowisp) and
applies `firmware/smk.patch` to smk. It needs `meson ninja boost bison flex` (Arch package
names), plus git, curl, Python 3, a C/C++ compiler and Rust.
