# Redragon K630 (single-colour) — hardware map and stock firmware notes

Derived from the stock firmware dump (`backup/k630-stock-firmware.hex`, firmware version
bcdDevice 12.10) with `re/dis8051.py`, plus `lsusb -v` and keypress tests on the real
keyboard. Addresses refer to that image. "Inferred" marks conclusions drawn from structure
rather than traced code.

## Summary

- The board is the same SinoWealth SH68F90A reference design as the **E-YOOSO Z11** (already
  supported by smk): identical row/column pins, Caps LED on P0.3, LED rows on P6.
- The stock firmware is a **generic Redragon build**: it scans 21 columns × 5 rows and
  carries a full-size keymap. The K630 (61-key 60 %, ANSI) uses columns 0–13.

## Key matrix

Active low: one column is driven low (the others float with pull-ups), and the rows are
read with pull-ups.

| Row | Pin | Keys (column) |
|---|---|---|
| 0 | P7.1 | Esc(0) 1 2 3 4 5 6 7 8 9 0 - = Bksp(13) |
| 1 | P7.2 | Tab(0) Q W E R T Y U I O P [ ] \\(13) |
| 2 | P7.3 | Caps(0) A S D F G H J K L ; '(11) Enter(13) |
| 3 | P5.3 | LShift(0) Z X C V B N M , . /(10) RShift(12) |
| 4 | P5.4 | LCtrl(0) LWin(1) LAlt(2) Space(5) RAlt(8) Fn/Menu(9,10) RCtrl(12) |

| Col | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Pin | P1.4 | P1.5 | P2.0 | P2.1 | P2.2 | P2.3 | P2.4 | P2.5 | P3.0 | P3.1 | P3.2 | P3.3 | P3.4 | P3.5 |

- The legends on the bottom row (from the keycaps) are Ctrl, Win, Alt, Space, Alt, Fn,
  Menu (with an arrow), Ctrl: 8 keys, so 61 in total.
- Raw test with keyd stopped (`keyd monitor`, 2026-11-14), pressing left to right: leftcontrol,
  leftmeta, leftalt, space, rightalt, *(Fn: nothing)*, compose (App 0x65), rightcontrol. This
  matches the modifier bitmasks in the stock tables.
- **Still open:** whether Fn is c9 and Menu is c10, or the reverse. Both carry the vendor code
  `0xB0` in the stock table. We assume Fn = c9 and Menu = c10 (as on the Z11) and verify after
  the first flash. A wrong guess only swaps those two keys.
- P7.0 is configured as an input but never read. In the generic table it is the F-key row,
  which a 60 % board does not have.
- Unused on the K630 but scanned by the stock firmware: columns 14–20 = P1.3, P1.2, P1.1, P1.0,
  P5.0, P5.1, P5.2 (the nav cluster and numpad on full-size Redragon boards).

## Clock

- Stock (`0x6527`): `CLKCON=HFON` → delay → `PLLCON=PLLON` → delay → `PLLCON=PLLON|PLLFS` →
  `CLKCON=HFON|FS`.
- smk's `clock_init()` ends with the same register values (`CLKCON=0x0C`, `PLLCON=0x03`), but
  it waits on `PLLSTA` in an unbounded loop that keeps kicking the watchdog. **Our build must
  bound that wait**, so a stuck PLL ends in the watchdog → ISP fallback instead of a hang.
- The watchdog is in use: the stock firmware clears `RSTSTAT` (the watchdog kick) during init.

## Backlight and indicators (not yet mapped in detail)

- Caps Lock LED: P0.3 (the same as the Z11).
- LED rows on P6.0–5 (stock `P6CR=0x3F`), driven by `0x5F06` and multiplexed with the key
  columns. PWM4 channels 0–2 are set from the PWM interrupt. The Z11 uses LED rows
  P6.1–5 with per-column PWM, which is probably the same here.
- Other outputs set at init, purpose unknown: P0.2, P0.4, P4.4, P5.5, P5.6, P7.5.

## USB

| Item | Location | Contents |
|---|---|---|
| Device descriptor | `0x0FCC` | USB 1.10, EP0 8 B, VID `258a` PID `002a`, bcdDevice `12.10`, strings 1/2, 1 configuration |
| Configuration descriptor | `0x0FDE` | 59 B, 2 interfaces, remote wakeup, 500 mA |
| Keyboard report descriptor (interface 0) | `0x0E7C` | boot keyboard, 6KRO |
| Vendor/composite report descriptor (interface 1) | `0x0EBF` | see below |
| Strings (UTF-16) | `0x0E30` "Gaming KB ", `0x0E46` "SINO WEALTH" | |

Interface 1 reports (from the report descriptor; purposes partly inferred):

| ID | Type | Size | Purpose |
|---|---|---|---|
| 1 | input | 1 B | system control (power/sleep/wake) |
| 2 | input | 2 B | consumer control (media keys) |
| 5 | feature | 5 B | ISP command: `0x75` reboots into the bootloader (sinowisp uses this) |
| 6 | input | 15 B | NKRO bitmap |
| 9 | feature | 504 B | inferred: keymap upload/download (126 keys × 4 B, the same format as flash `0xC600`) |
| 10 | feature | 41 B | inferred: settings (LED mode, brightness, …) |
| 11 | feature | 126 B | inferred: one byte per key position (per-key LED or key type) |
| 12 | feature | 1920 B | inferred: macros |
| 13 | input | 6 B | mouse (buttons, X/Y, wheel, AC pan), used by macros |

## Flash layout

| Range | Contents |
|---|---|
| `0x0000`–`0x66EB` | code and constant data (~26 KB) |
| `0x6800`–`0xC5FF` | blank |
| `0xC600`–`0xC7F7` | saved keymap, 126 × 4 B: [type, modifier mask, HID usage, 0]. This is where Redragon's software stores remaps. |
| `0xC800`… | settings record: `5A 04 01 01 02 …` (`0x5A` = valid marker, inferred) |
| `0xEFFB`–`0xEFFF` | app reset vector kept for the bootloader (sinowisp moves it to `0x0000` in dumps) |
| `0xF000`–`0xFFFF` | ISP bootloader, MD5 `3e0ebd0c440af5236d7ff8872343f85d` |

The stock firmware **writes its own flash at runtime** (settings and remaps):
- sector erase at `0x6060` (`IB_CON1=0xE6`)
- byte program at `0x5EDB` (`IB_CON1=0x6E`)
- both use the unlock sequence `IB_CON2..5 = 05 0A 09 06`, the same as smk's `flash.c`.

## Keymap tables

- **Default keymap** at `0x54C2`: 126 B (21 columns × 6 rows), column-major
  (`index = col*6 + row`, row 0 = the unused F row), HID usages only. Modifiers are 0 here.
- **Runtime keymap** in XRAM `0x07D5`: 4 B per key. It is copied from the defaults by `0x56A7`
  and loaded from / saved to flash `0xC600`.
- **Modifier positions** (byte 1 of each flash entry, as a bitmask):
  - LCtrl c0r4 (`0x01`), LShift c0r3 (`0x02`), LAlt c2r4 (`0x04`), LWin c1r4 (`0x08`)
  - RCtrl c12r4 (`0x10`), RShift c12r3 (`0x20`), RAlt c8r4 (`0x40`)
- **`0xB0` = Fn marker.** It is never sent to the host and is stripped from reports at
  `0x07DA` and `0x6131`. Under some condition `0x6388` puts App (`0x65`) in a report slot,
  inferred to be the Menu key.
- **Stock Fn layer** (`0x07xx`–`0x09xx`). It uses a row-major index (`row*21 + col`):
  - Fn + Esc = `` ` ``, Fn + 1…= = F1…F12
  - Fn + W/A/S/D = Up/Left/Down/Right
  - Fn + P = PrtSc, Fn + [ = Home, Fn + ] = End, Fn + ; = PgUp, Fn + ' = PgDn
  - Fn + . = Ins, Fn + / = Del

## Firmware structure

| What | Address |
|---|---|
| Reset → app entry | `0x4F35` |
| Interrupt vectors in use | 0x03 Timer2 (`0x6396`), 0x0B INT4 wake (`0x66CE`), 0x13, 0x1B, 0x3B USB (`0x5F4A`), 0x43 PWM (`0x5784`) |
| Timer2 tick: counters, sets the "scan due" flag every 2 ticks | `0x6396` |
| Port init (P0CR=1C P1CR=3F P2CR=3F P3CR=3B P4CR=10 P5CR=67 P6CR=3F P7CR=20, pull-ups, 25 mA drive on P1/P2/P3/P5) | `0x57F0` |
| Column select/deselect (21-case switch) | `0x0046`, jump table `0x0062` |
| Row read (two samples, keeps a bit only if both agree) | `0x5717` |
| Scan loop: per column select → 1 delay unit → read → store IRAM `0x60+col` → deselect | `0x5C0B` |
| Sleep: all columns low, rows pulled up, INT4 wake, PLL off, `PCON` power-down | `0x48E9` |
| Clock init | `0x6527` |
| LED row driver (P6) | `0x5F06` |
| Flash erase / program | `0x6060` / `0x5EDB` |
| Delay routine (R6:R7 units) | `0x62DD` |

Disassembly notes: `re/dis8051.py` follows code from the reset vector, the vectors that hold
a jump, and switch jump tables. That covers 29,901 instructions in 125 functions. Two
function-pointer calls (`0x3876`, `0x3896`) are not followed.
