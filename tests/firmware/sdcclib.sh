#!/usr/bin/env bash
# Compile the SDCC library helpers the firmware links (memcpy, memcmp, memset, generic
# pointer access, 16-bit multiply) to assembly with the firmware's memory model, so
# stack_bound.py can analyse them too. Output: build/smk/sdcclib.asm.p/
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
L="$ROOT/third_party/sdcc-src/sdcc-4.5.0-compiler/sdcc-4.5.0/device"
O="$ROOT/build/smk/sdcclib.asm.p"
mkdir -p "$O"
for f in __memcpy memcpy _memcmp _memset _gptrget _gptrput _mulint; do
    "$ROOT/tools/bin/sdcc" -mmcs51 --model-large --stack-auto --std-c23 \
        -I"$L/include" -I"$L/include/mcs51" -S "$L/lib/$f.c" -o "$O/$f.asm"
done
