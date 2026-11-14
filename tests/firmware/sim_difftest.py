#!/usr/bin/env python3
"""Differential test of the real firmware image (in uCsim) against keyd v2.6.0.

Each script (tests/scripts/*.keys, then random and scenario scripts from
tests/difftest.py) is replayed through keyd's own core (tools/bin/keyd-oracle) and
through the K630 firmware running in the simulator: key presses go into the matrix,
time into the USB SOF clock, and the USB reports that come out are decoded back into
key events. The two event sequences must be identical.

Menu (FN2) is left out of the generated scripts: it is not a keyd key on the K630 (tap
= Menu, hold = FN2 layer) and has its own test (test_k630.py).

usage: sim_difftest.py [--config keymap/rynsf.conf] [--random 200] [--seed 1] [--pins N] [--jobs J]
  --pins N: replay the first N scripts through the pin-level matrix scan (slow) instead
            of writing the scan result directly.
"""
import argparse
import random
import subprocess
import sys
import tempfile
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tests"))

import difftest  # noqa: E402  (script generators)
from k630sim import K630Sim, one_media_slot  # noqa: E402

difftest.K630_KEYS = [k for k in difftest.K630_KEYS if k != "compose"]
ORACLE = ROOT / "tools/bin/keyd-oracle"


def oracle(config, script_path):
    p = subprocess.run([str(ORACLE), str(config), str(script_path)],
                       capture_output=True, text=True, timeout=20)
    if p.returncode:
        raise RuntimeError(p.stderr)
    return [tuple(line.split()[1:3]) for line in p.stdout.splitlines() if line.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="keymap/rynsf.conf")
    ap.add_argument("--random", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--pins", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=min(12, os.cpu_count() or 1),
                    help="simulators run side by side")
    args = ap.parse_args()
    config = (ROOT / args.config).resolve()

    scripts = [(p.name, p.read_text()) for p in sorted((ROOT / "tests/scripts").glob("*.keys"))]
    rng = random.Random(args.seed)
    for i in range(args.random):
        text = (difftest.scenario_script(rng) if rng.random() < 0.6
                else difftest.random_script(rng, rng.randint(2, 24)))
        scripts.append((f"random-{args.seed}-{i}", text))

    def run_one(job):
        """One script, in its own freshly booted simulator (no state shared between scripts)."""
        n, name, text = job
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "s.keys"
            path.write_text(text)
            want = one_media_slot(oracle(config, path))
        sim = K630Sim()
        try:
            sim.boot_configured()
            sim.paint_stack()
            got = [tuple(e) for e in sim.play(text, direct=n >= args.pins)]
            used = sim.stack_highwater()
        finally:
            sim.close()
        return name, text, want, got, used

    # The simulator is latency-bound (one socket round trip per command, ~1% CPU), so
    # several sessions run side by side; each script still gets its own fresh boot.
    jobs = [(n, name, text) for n, (name, text) in enumerate(scripts) if "compose" not in text]
    fails = []
    peak = (0, None)  # deepest stack seen: (bytes, script)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for name, text, want, got, used in pool.map(run_one, jobs):
            if used > peak[0]:
                peak = (used, name)
            if got != want:
                fails.append((name, text, want, got))
    scripts = jobs

    print(f"firmware vs keyd: {len(scripts) - len(fails)}/{len(scripts)} identical "
          f"(seed {args.seed}, first {args.pins} via pin-level scan)")
    print(f"deepest stack: {peak[0]} bytes ({peak[1]})")
    if fails:
        out = ROOT / "tests/failures"
        out.mkdir(exist_ok=True)
        for name, text, want, got in fails[:20]:
            (out / f"sim-{name}.keys").write_text(text)
            print(f"  FAIL {name}\n    keyd:     {want}\n    firmware: {got}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
