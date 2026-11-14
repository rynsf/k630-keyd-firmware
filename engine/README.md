# kd: keyd's key engine for the K630

`kd.c` is a port of keyd v2.6.0's `src/keyboard.c` (MIT, see `LICENSE.keyd`) that runs on
the SH68F90 (SDCC 4.5.0, large model) and on the host. `kd_config.h` describes the compiled
config tables. They are generated from a keyd config by `tools/keyd-oracle/export.c`, which
uses keyd's own parser and refuses anything the engine doesn't implement.

The differences from keyd are listed at the top of `kd.c`. The main one is that keyd's
recursion is replaced by an explicit frame stack in XRAM.

## Testing

    make test          # both configs, 5000 random + scripted sequences each
    make test-config CONFIG=keymap/rynsf.conf RANDOM=20000 SEED=7

`tests/difftest.py` replays every script through keyd itself (`tools/bin/keyd-oracle`: keyd's
core driven the way the daemon drives it) and through the engine (`build/<config>/kd-host`),
and requires byte-identical output. The random sequences are physically valid (no key pressed
twice while held) and clustered around the timing thresholds. They include targeted fragments
for holds, rolls, nested tap/hold keys, layout switching, one-shot timing and the modifier
guard.

`tests/configs/coverage.conf` exercises the supported actions that `rynsf.conf` does not use.
A mutation check (7 deliberate engine bugs) is caught by these tests.

## Footprint (SDCC 4.5.0, rynsf.conf)

~7.3 KB code + 0.7 KB tables, 1.9 KB XRAM, 0 B internal RAM (stack only).
