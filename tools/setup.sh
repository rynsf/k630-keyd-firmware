#!/usr/bin/env bash
# Rebuild the toolchain from scratch: sinowisp, patched uCsim (SH68F90), SDCC 4.5.0.
# Needs pacman packages: meson ninja boost bison flex. The build uses a local SDCC 4.5.0
# (the version smk is tested with); Arch's sdcc 4.6.0 rejects smk's code.
# Nothing here talks to the keyboard.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TP="$ROOT/third_party"
mkdir -p "$TP" "$ROOT/tools/bin"

SINOWISP_REV=242f7921357bad6df649efdd70c49dd059567ac7
SMK_REV=dbd5c54e7607dfd584da3d4690b6d113925c976a
SINODUDE_REV=2419ec17097e73478b8414816fef65e60dba5fae
SDCC_VER=4.5.0
SDCC_SHA256=d5030437fb436bb1d93a8dbdbfb46baaa60613318f4fb3f5871d72815d1eed80

clone() { # name url rev
    # GIT_CONFIG_GLOBAL=/dev/null: a global config may rewrite https→ssh
    [ -d "$TP/$1" ] || GIT_CONFIG_GLOBAL=/dev/null git clone -q "$2" "$TP/$1"
    GIT_CONFIG_GLOBAL=/dev/null git -C "$TP/$1" fetch -q --depth 200 origin || true
    git -C "$TP/$1" checkout -q "$3"
}
clone sinowisp https://github.com/karstx/sinowisp "$SINOWISP_REV"
clone smk      https://github.com/karstx/smk      "$SMK_REV"
clone sinodude https://github.com/karstx/sinodude "$SINODUDE_REV"

# sinowisp (ISP flasher)
(cd "$TP/sinowisp" && cargo build --release)
ln -sf "$TP/sinowisp/target/release/sinowisp" "$ROOT/tools/bin/sinowisp"

# SDCC source
mkdir -p "$TP/sdcc-src" && cd "$TP/sdcc-src"
TARBALL="sdcc-src-$SDCC_VER.tar.bz2"
[ -f "$TARBALL" ] || curl -sSL -o "$TARBALL" "https://downloads.sourceforge.net/project/sdcc/sdcc/$SDCC_VER/$TARBALL"
echo "$SDCC_SHA256  $TARBALL" | sha256sum -c -

# patched uCsim
rm -rf "sdcc-$SDCC_VER" && tar xjf "$TARBALL"
cd "sdcc-$SDCC_VER"
patch -p1 -s < "$TP/smk/tools/ucsim/sh68f90-register.patch"
cp "$TP/smk/tools/ucsim/sh68f90.cc" "$TP/smk/tools/ucsim/sh68f90cl.h" sim/ucsim/src/sims/s51.src/
flex -o sim/ucsim/src/core/cmd.src/cmdlex.cc sim/ucsim/src/core/cmd.src/cmdlex.l
cd sim/ucsim
./configure --enable-avr-sim=no --enable-f8-sim=no --enable-i8048-sim=no --enable-i8085-sim=no \
    --enable-m6800-sim=no --enable-m6809-sim=no --enable-m68hc08-sim=no --enable-m68hc11-sim=no \
    --enable-m68hc12-sim=no --enable-mos6502-sim=no --enable-oisc-sim=no --enable-p1516-sim=no \
    --enable-pblaze-sim=no --enable-pdk-sim=no --enable-rxk-sim=no --enable-st7-sim=no \
    --enable-stm8-sim=no --enable-tlcs-sim=no --enable-xa-sim=no --enable-z80-sim=no >/dev/null
make -j"$(nproc)" >/dev/null
ln -sf "$PWD/src/sims/s51.src/ucsim_51" "$ROOT/tools/bin/ucsim-sh68f90"

# SDCC 4.5.0 compiler (gnu17: 4.5.0's linker sources predate GCC 15's C23 default;
# the z80 port stays enabled because 4.5.0's build breaks with it disabled)
cd "$TP/sdcc-src" && rm -rf "sdcc-$SDCC_VER-compiler" && mkdir "sdcc-$SDCC_VER-compiler"
tar xjf "$TARBALL" -C "sdcc-$SDCC_VER-compiler" && cd "sdcc-$SDCC_VER-compiler/sdcc-$SDCC_VER"
CFLAGS="-O2 -std=gnu17" ./configure --prefix="$ROOT/tools/sdcc-$SDCC_VER" \
    --disable-pic14-port --disable-pic16-port --disable-ucsim --disable-sdcdb --disable-non-free >/dev/null
make -j"$(nproc)" >/dev/null && make install >/dev/null
for t in sdcc sdar packihx sdas8051 sdld sdcpp; do
    ln -sf "$ROOT/tools/sdcc-$SDCC_VER/bin/$t" "$ROOT/tools/bin/$t"
done

echo "done. run: source tools/env.sh"
