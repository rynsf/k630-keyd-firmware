# Redragon K630 (single-colour) — hardware map

Derived from the stock firmware dump (`backup/k630-stock-firmware.hex`) with
`re/dis8051.py`. Addresses refer to that image.

## Summary

The board is the same SinoWealth reference design as the **E-YOOSO Z11** (already in smk):
identical matrix row/column pins, Caps LED on P0.3, LED rows on P6. The stock firmware is a
generic Redragon build: it scans 21 columns × 5 rows and carries a full-size keymap, of
which the K630 uses columns 0–13.

## Key matrix (active low: drive one column low, read rows with pull-ups)

| Row | Pin | Keys |
|---|---|---|
| 0 | P7.1 | Esc 1 2 3 4 5 6 7 8 9 0 - = Bksp |
| 1 | P7.2 | Tab Q W E R T Y U I O P [ ] \ |
| 2 | P7.3 | Caps A S D F G H J K L ; ' (c12 #iso) Enter(c13) |
| 3 | P5.3 | LShift(c0) Z X C V B N M , . / (c11 ?87) RShift(c12) |
| 4 | P5.4 | LCtrl(c0) LGui(c1) LAlt(c2) Space(c5) RAlt(c8) 0xB0(c9) 0xB0(c10) RCtrl(c12) |

P7.0 is configured as an input but never read: in the generic table it is the F-key row,
which a 60 % board does not have.

| Col | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Pin | P1.4 | P1.5 | P2.0 | P2.1 | P2.2 | P2.3 | P2.4 | P2.5 | P3.0 | P3.1 | P3.2 | P3.3 | P3.4 | P3.5 |

The stock firmware also scans columns 14–20 (P1.3, P1.2, P1.1, P1.0, P5.0, P5.1, P5.2), which
hold the nav cluster and numpad on full-size Redragon boards.

**To confirm on the hardware:** the bottom row right of Space. The stock table puts RCtrl at
c12 (the Z11 has it at c11, with Fn at c9 and App at c10). `0xB0` is a vendor code; one
is probably Fn.

## Where things are in the stock image

| What | Address |
|---|---|
| Reset → app entry | `0x4F35` |
| Vectors used | 0x03 Timer2 tick (`0x6396`), 0x0B INT4 wake (`0x66CE`), 0x13, 0x1B, 0x3B USB (`0x5F4A`), 0x43 PWM (`0x5784`) |
| Port init | `0x57F0` (P0CR=1C P1CR=3F P2CR=3F P3CR=3B P4CR=10 P5CR=67 P6CR=3F P7CR=20) |
| Column select/deselect switch (21 cases) | `0x0046`, table `0x0062` |
| Row read (with double-sample debounce) | `0x5717` |
| Scan loop (stores row bytes at IRAM 0x60+col) | `0x5C0B` |
| Default keymap, 21 col × 6 row, HID usages | `0x54C2` (index = col*6 + row) |
| Saved keymap (4 B/key: type, modifier mask, usage, 0) | flash `0xC600` |
| Sleep: all columns low, rows pull-up, wake on INT4 | `0x48E9` |
| Clock init | `0x6527` |
| LED row driver (P6) | `0x5F06` |

## Clock

Stock: `CLKCON=HFON` → delay → `PLLCON=PLLON` → delay → `PLLCON=PLLON|PLLFS` →
`CLKCON=HFON|FS`. smk's `clock_init()` ends in the same register values, but it waits on
`PLLSTA` in an unbounded loop. Our build must bound that wait so a stuck PLL ends in the
watchdog → ISP fallback.

## Backlight (not yet mapped in detail)

- Caps Lock LED: P0.3 (as on the Z11).
- LED rows on P6.0–5 (stock P6CR=0x3F), multiplexed with the key columns; PWM4 channels 0–2
  set in the PWM ISR. The Z11 uses LED rows P6.1–5 with per-column PWM, which is likely the same.
