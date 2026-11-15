#!/usr/bin/env bash
# Flash a K630 image after the pre-flash checks; refuses if any check fails.
#   tools/flash.sh <image.hex> <expected sha256>
#   tools/flash.sh --identify          only say what is connected and whether it may be flashed
#
# Overrides (each only when you know why):
#   K630_ALLOW_BATTERY=1   flash without AC power, if the battery is at least 50%
#   K630_ISP_MODE_OK=1     flash a keyboard that is already in update mode (0603:1020). That
#                          bootloader looks the same on every SinoWealth board, so the script
#                          cannot tell it is a K630: only for recovering *this* keyboard.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

STOCK_BACKUP="$ROOT/backup/k630-stock-firmware.hex"
STOCK_MD5=5be9da99f9f9228e814df3a2e9cbb287 # the 61440 bytes of the stock K630 firmware 12.10

usb_attr() { cat "$1/$2" 2>/dev/null || true; }

# What is connected: "ours", "stock", "isp", or "none"/"unknown: ..." (and why).
identify() {
    local found=none d
    for d in "${K630_USB_SYSFS:-/sys/bus/usb/devices}"/*; do  # (override: tests only)
        [ -f "$d/idVendor" ] || continue
        local id
        id="$(usb_attr "$d" idVendor):$(usb_attr "$d" idProduct)"
        case "$id" in
            258a:002a)
                local bcd man prod
                bcd=$(usb_attr "$d" bcdDevice) man=$(usb_attr "$d" manufacturer) prod=$(usb_attr "$d" product)
                if [ "$man" = "contact@carlossless.io" ] && [ "$prod" = "SMK Keyboard" ]; then
                    found=ours
                elif [ "$bcd" = "1210" ]; then
                    found=stock
                else
                    found="unknown: 258a:002a with bcdDevice $bcd, \"$man\" \"$prod\" (not the K630 firmware this was built for)"
                fi
                ;;
            0603:1020) found=isp ;;
        esac
    done
    echo "$found"
}

stock_backup_ok() {
    [ -f "$STOCK_BACKUP" ] || return 1
    python3 - "$STOCK_BACKUP" "$STOCK_MD5" <<'EOF'
import hashlib, sys
d = bytearray(61440)
for l in open(sys.argv[1]):
    if l[7:9] == "00":
        n, a = int(l[1:3], 16), int(l[3:7], 16)
        d[a:a + n] = bytes.fromhex(l[9:9 + 2 * n])
sys.exit(0 if hashlib.md5(d).hexdigest() == sys.argv[2] else 1)
EOF
}

# May this device be flashed? Prints the reason when not.
device_ok() {
    local what
    what=$(identify)
    case "$what" in
        ours) echo "connected: K630 running this project's firmware"; return 0 ;;
        stock)
            echo "connected: K630 running the stock firmware (bcdDevice 12.10)"
            if ! stock_backup_ok; then
                echo "refusing: no backup of this keyboard's stock firmware matching the known K630"
                echo "  firmware (MD5 $STOCK_MD5). Back it up first: see backup/README.md."
                echo "  A different MD5 means a different board or firmware version: this image"
                echo "  was not built for it."
                return 1
            fi
            return 0
            ;;
        isp)
            echo "connected: a SinoWealth keyboard in update mode (0603:1020)"
            if [ "${K630_ISP_MODE_OK:-0}" != 1 ]; then
                echo "refusing: update mode looks the same on every SinoWealth board. Replug the"
                echo "  keyboard (it normally starts its firmware again), or, if this is the K630"
                echo "  and it stays in update mode, rerun with K630_ISP_MODE_OK=1."
                return 1
            fi
            return 0
            ;;
        none) echo "refusing: keyboard not found"; return 1 ;;
        *) echo "refusing: $what"; return 1 ;;
    esac
}

if [ "${1:-}" = "--identify" ]; then
    device_ok && echo "ok to flash" || true
    exit 0
fi

img="$1"; want="$2"
if [ "$(cat /sys/class/power_supply/AC0/online 2>/dev/null || echo 0)" != 1 ]; then
  # K630_ALLOW_BATTERY=1: flash on battery anyway, if it is at least 50%
  bat="$(cat /sys/class/power_supply/BAT0/capacity 2>/dev/null || echo 0)"
  [ "${K630_ALLOW_BATTERY:-0}" = 1 ] && [ "$bat" -ge 50 ] || { echo "refusing: not on mains power (battery ${bat}%)"; exit 1; }
  echo "on battery (${bat}%), allowed by K630_ALLOW_BATTERY"
fi
[ "$(sha256sum "$img" | cut -d' ' -f1)" = "$want" ] || { echo "refusing: image hash differs"; exit 1; }
python3 "$ROOT/tests/firmware/check_no_flash_write.py" "$img"
device_ok || exit 1
PATH="$ROOT/tools/bin:$PATH" sinowisp write -d redragon-k630-norgb -f "$img"
