# Redragon K630 (single-colour, pink) — stock flash backup

Read on 2026-11-14 with sinowisp 2.1.0 (`-d redragon-k630-norgb`) over the stock ISP bootloader.

| | |
|---|---|
| USB ID (normal / ISP) | `258a:002a` / `0603:1020` |
| Firmware version (bcdDevice) | 12.10 |
| MCU | SinoWealth SH68F90 / SH68F90A (64 KiB flash, 4 KiB XRAM) |
| Bootloader | top 4 KiB (`0xf000`–`0xffff`), MD5 `3e0ebd0c440af5236d7ff8872343f85d` (known, supported by sinowisp) |
| Firmware used | ends at `0xc804` |

## Files

| File | Contents | MD5 |
|---|---|---|
| `k630-stock-full.bin` | full 64 KiB: firmware + bootloader (sinowisp file layout) | `bbc146cabd38bb0e97ab287eae95401c` |
| `k630-stock-firmware.hex` | firmware section only (61440 bytes), Intel HEX: **use this to restore** | read MD5 `5be9da99f9f9228e814df3a2e9cbb287` |

Two separate full reads were byte-identical, and the firmware-only read matches the
first 61440 bytes of the full read.

In sinowisp's file layout the real reset vector sits at `0x0000`
(`02 4f 35` = LJMP 0x4f35). On the chip itself, `0x0000` jumps into the bootloader and the
app vector is kept near `0xeffb`. sinowisp converts between the two on read and write.

## Restore stock firmware (stock bootloader untouched)

    sinowisp write -d redragon-k630-norgb backup/k630-stock-firmware.hex

This only works if the keyboard can still get into ISP mode: either the running firmware
honours the ISP-jump command, or there is no valid firmware. Otherwise use ICP
(sinodude + Arduino Nano).
