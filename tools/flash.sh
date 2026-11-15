#!/usr/bin/env bash
# Flash a K630 image after the pre-flash checks; refuses if any check fails.
#   tools/flash.sh <image.hex> <expected sha256>
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
img="$1"; want="$2"
if [ "$(cat /sys/class/power_supply/AC0/online)" != 1 ]; then
  # K630_ALLOW_BATTERY=1: flash on battery anyway, if it is at least 50%
  bat="$(cat /sys/class/power_supply/BAT0/capacity)"
  [ "${K630_ALLOW_BATTERY:-0}" = 1 ] && [ "$bat" -ge 50 ] || { echo "refusing: not on mains power (battery ${bat}%)"; exit 1; }
  echo "on battery (${bat}%), allowed by K630_ALLOW_BATTERY"
fi
[ "$(sha256sum "$img" | cut -d' ' -f1)" = "$want" ] || { echo "refusing: image hash differs"; exit 1; }
python3 "$ROOT/tests/firmware/check_no_flash_write.py" "$img"
lsusb | grep -qE "258a:002a|0603:1020" || { echo "refusing: keyboard not found"; exit 1; }
PATH="$ROOT/tools/bin:$PATH" sinowisp write -d redragon-k630-norgb -f "$img"
