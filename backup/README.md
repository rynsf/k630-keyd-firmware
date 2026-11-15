# Redragon K630 (single-colour, pink) — stock flash backup

**The stock firmware is not in this repository** (it is Redragon's / SinoWealth's code, not
ours to redistribute; `backup/*.hex` and `*.bin` are gitignored). **Back up your own
keyboard before flashing anything**, while it still runs the stock firmware:

    PATH=$PWD/tools/bin:$PATH sinowisp read -d redragon-k630-norgb -s firmware --format ihex backup/k630-stock-firmware.hex
    PATH=$PWD/tools/bin:$PATH sinowisp read -d redragon-k630-norgb -s full --format bin backup/k630-stock-full.bin

Read it twice and compare: both reads must be identical. The MD5s below are those of the
author's keyboard (read on 2026-11-14 with sinowisp 2.1.0). If yours differ, your board or
firmware version is different from the one this project was built and tested on: stop and
check `re/K630-HARDWARE.md` against your own dump before going further.

| | |
|---|---|
| USB ID (normal / ISP) | `258a:002a` / `0603:1020` |
| Firmware version (bcdDevice) | 12.10 |
| MCU | SinoWealth SH68F90 / SH68F90A (64 KiB flash, 4 KiB XRAM) |
| Bootloader | top 4 KiB (`0xf000`–`0xffff`), MD5 `3e0ebd0c440af5236d7ff8872343f85d` (known, supported by sinowisp) |
| Firmware used | code `0x0000`–`0x66EB`; saved keymap + settings `0xC600`–`0xC80F` (see `re/K630-HARDWARE.md`) |

## Files

| File | Contents | MD5 |
|---|---|---|
| `k630-stock-full.bin` | full 64 KiB: firmware + bootloader (sinowisp file layout) | `bbc146cabd38bb0e97ab287eae95401c` |
| `k630-stock-firmware.hex` | firmware section only (61440 bytes), Intel HEX: **use this to restore** | MD5 of the 61440 bytes it holds: `5be9da99f9f9228e814df3a2e9cbb287` |

Two separate full reads were byte-identical, and the firmware-only read matches the
first 61440 bytes of the full read.

In sinowisp's file layout the real reset vector sits at `0x0000`
(`02 4f 35` = LJMP 0x4f35). On the chip itself, `0x0000` jumps into the bootloader and the
app vector is kept near `0xeffb`. sinowisp converts between the two on read and write.

## Restore stock firmware (stock bootloader untouched)

    PATH=$PWD/tools/bin:$PATH sinowisp write -d redragon-k630-norgb -f backup/k630-stock-firmware.hex

This only works if the keyboard can still get into ISP mode: either the running firmware
honours the ISP-jump command, or there is no valid firmware. Otherwise use ICP
(sinodude + Arduino Nano).
