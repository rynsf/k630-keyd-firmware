#!/usr/bin/env python3
"""Differential test: firmware engine (build/<config>/kd-host, built by make) vs keyd v2.6.0 (tools/bin/keyd-oracle).

Runs every hand-written script in tests/scripts/*.keys, then N random but physically valid
key sequences over the K630's keys, with timings clustered around the config's thresholds.
Any difference is saved to tests/failures/ and reported; exit status 1 if any.

usage: difftest.py [--config keymap/rynsf.conf] [--random 3000] [--seed 1]
"""
import argparse
import os
import random
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ORACLE = ROOT / "tools/bin/keyd-oracle"
HOST = Path(os.environ.get("KD_HOST", ROOT / "build/rynsf/kd-host"))  # make sets KD_HOST

# The 61 keys of the K630, by keyd name (Fn never reaches keyd: handled in firmware).
K630_KEYS = (
    "esc 1 2 3 4 5 6 7 8 9 0 - = backspace "
    "tab q w e r t y u i o p [ ] \\ "
    "capslock a s d f g h j k l ; ' enter "
    "leftshift z x c v b n m , . / rightshift "
    "leftcontrol leftmeta leftalt space rightalt compose rightcontrol"
).split()

# Keys whose bindings carry the interesting behaviour get picked more often.
HOT = "capslock enter space tab leftshift rightshift leftalt leftmeta rightalt 1 2 " \
      "q w e r t a s d f g z x c v b j k l ; ' u i o p m , . /".split()

DELAYS = [0, 0, 1, 2, 5, 10, 20, 30, 50, 80, 100, 120, 150, 170, 174, 175, 176, 180, 200,
          250, 300, 350, 399, 400, 401, 450, 600, 1000]


def run(binary_args, script):
    p = subprocess.run(binary_args + [str(script)], capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout, p.stderr


def compare(config, script):
    rc1, out1, err1 = run([str(ORACLE), str(config)], script)
    rc2, out2, err2 = run([str(HOST)], script)
    if rc1 != 0:
        return f"oracle failed: {err1.strip()}"
    if rc2 != 0 or "ERROR" in err2 or "runtime error" in err2:
        return f"engine failed (rc={rc2}): {err2.strip()}"
    if "kd_overflow" in err2:
        return f"engine overflow: {err2.strip()}"
    if out1 != out2:
        return "output differs"
    return None


def random_script(rng, n_actions):
    held = []
    lines = []
    for _ in range(n_actions):
        d = rng.choice(DELAYS)
        if d:
            lines.append(f"{d}ms")
        if held and (len(held) >= 4 or rng.random() < 0.5):
            k = held.pop(rng.randrange(len(held)))
            lines.append(f"{k} up")
        else:
            pool = HOT if rng.random() < 0.8 else K630_KEYS
            k = rng.choice([k for k in pool if k not in held])
            held.append(k)
            lines.append(f"{k} down")
    rng.shuffle(held)
    for k in held:
        d = rng.choice(DELAYS)
        if d:
            lines.append(f"{d}ms")
        lines.append(f"{k} up")
    return "\n".join(lines) + "\n"


OVERLOADS = ["capslock", "enter", "space", "tab"]
LAYER_KEYS = "q w e r t a s d f g z x c v b j k l ; ' u i o p m , . / 1 2".split()
SHORT = [0, 1, 5, 20, 50, 100, 150, 170, 174]
LONG = [175, 176, 180, 200, 300, 500]


def frag_hold(rng):
    """overload key held past the threshold, keys tapped inside the layer"""
    o = rng.choice(OVERLOADS)
    out = [f"{o} down", f"{rng.choice(LONG)}ms"]
    for _ in range(rng.randint(1, 3)):
        k = rng.choice(LAYER_KEYS)
        out += [f"{k} down", f"{rng.choice(SHORT)}ms", f"{k} up", f"{rng.choice(SHORT)}ms"]
    return out + [f"{o} up"]


def frag_roll(rng):
    """overload key and a key overlapping inside the window, released in either order"""
    o, k = rng.choice(OVERLOADS), rng.choice(LAYER_KEYS)
    ev = [f"{o} down", f"{rng.choice(SHORT)}ms", f"{k} down", f"{rng.choice(SHORT)}ms"]
    tail = [f"{o} up", f"{k} up"]
    if rng.random() < 0.5:
        tail.reverse()
    return ev + [tail[0], f"{rng.choice(SHORT + LONG)}ms", tail[1]]


def frag_nested(rng):
    """two or three overload keys pressed inside each other's window"""
    os_ = rng.sample(OVERLOADS, rng.randint(2, 3))
    out = []
    for o in os_:
        out += [f"{o} down", f"{rng.choice(SHORT)}ms"]
    for _ in range(rng.randint(0, 2)):
        k = rng.choice(LAYER_KEYS)
        out += [f"{k} down", f"{rng.choice(SHORT)}ms", f"{k} up", f"{rng.choice(SHORT + LONG)}ms"]
    rng.shuffle(os_)
    for o in os_:
        out += [f"{o} up", f"{rng.choice(SHORT + LONG)}ms"]
    return out


def frag_layout(rng):
    """tab held (switch layer) + 1 or 2"""
    n = rng.choice(["1", "2"])
    return ["tab down", f"{rng.choice(SHORT + LONG)}ms", f"{n} down", f"{rng.choice(SHORT)}ms",
            f"{n} up", f"{rng.choice(SHORT)}ms", "tab up"]


def frag_oneshot(rng):
    s, k = rng.choice(["leftshift", "rightshift"]), rng.choice(LAYER_KEYS + OVERLOADS)
    return [f"{s} down", f"{rng.choice(SHORT)}ms", f"{s} up",
            f"{rng.choice([0, 50, 200, 399, 400, 401, 600])}ms",
            f"{k} down", f"{rng.choice(SHORT + LONG)}ms", f"{k} up"]


def frag_mods(rng):
    """lone or combined modifier taps (modifier guard), Alt/Win swap, rightalt = control"""
    m = rng.sample(["leftalt", "leftmeta", "rightalt", "leftcontrol", "rightcontrol"], rng.randint(1, 2))
    out = [f"{x} down" for x in m] + [f"{rng.choice(SHORT)}ms"]
    if rng.random() < 0.5:
        k = rng.choice(LAYER_KEYS)
        out += [f"{k} down", f"{k} up"]
    return out + [f"{x} up" for x in reversed(m)]


FRAGS = [frag_hold, frag_roll, frag_nested, frag_layout, frag_oneshot, frag_mods]


def scenario_script(rng):
    lines = []
    for _ in range(rng.randint(1, 6)):
        if rng.random() < 0.25:
            lines += random_script(rng, rng.randint(2, 8)).split()
            # random_script() lines are "<key> <state>" or "<n>ms": re-join pairs
        else:
            lines += rng.choice(FRAGS)(rng)
        lines.append(f"{rng.choice(DELAYS)}ms")
    # re-assemble tokens split from random_script into lines
    out, i = [], 0
    while i < len(lines):
        tok = lines[i]
        if tok.endswith("ms") and tok[:-2].isdigit():
            out.append(tok)
            i += 1
        elif tok.endswith((" down", " up")):
            out.append(tok)
            i += 1
        else:
            out.append(f"{tok} {lines[i + 1]}")
            i += 2
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="keymap/rynsf.conf")
    ap.add_argument("--random", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()
    config = (ROOT / args.config).resolve()

    failures = []
    fail_dir = ROOT / "tests/failures"

    scripts = sorted((ROOT / "tests/scripts").glob("*.keys"))
    for s in scripts:
        why = compare(config, s)
        if why:
            failures.append((s.name, why, s.read_text()))
    print(f"scripted: {len(scripts) - sum(1 for f in failures)}/{len(scripts)} identical")

    rng = random.Random(args.seed)
    n_bad = 0
    with tempfile.TemporaryDirectory() as tmp:
        for i in range(args.random):
            if rng.random() < 0.6:
                text = scenario_script(rng)
            else:
                text = random_script(rng, rng.randint(2, 24))
            path = Path(tmp) / "r.keys"
            path.write_text(text)
            why = compare(config, path)
            if why:
                n_bad += 1
                failures.append((f"random-{args.seed}-{i}.keys", why, text))
    print(f"random:   {args.random - n_bad}/{args.random} identical (seed {args.seed})")

    if failures:
        fail_dir.mkdir(exist_ok=True)
        for name, why, text in failures[:50]:
            (fail_dir / name).write_text(text)
            print(f"  FAIL {name}: {why}")
        print(f"{len(failures)} failure(s); scripts saved in {fail_dir}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
