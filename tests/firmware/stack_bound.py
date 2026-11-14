#!/usr/bin/env python3
"""Static worst-case stack bound for the firmware image, from SDCC's generated assembly.

For every function in the build's .asm files it follows the control flow, tracking the
stack-pointer offset of each instruction (push/pop, inc/dec sp, `mov sp,a` after
`add a,#k`, calls). Through the call graph that gives the deepest stack any path can reach
from `main` and from each interrupt handler. Interrupts all share one priority (no IP
register is ever written), so they cannot nest: worst case = main + deepest ISR.

Fails on what it cannot bound: indirect calls, unbalanced control-flow merges, recursion
of any kind, and functions it cannot find.

usage: stack_bound.py <stack bytes available> <asm dir>...
  asm dirs: the image's <target>.ihx.p, smk's user.lib.p, and the SDCC library helpers
  compiled to assembly with the firmware's flags (see tests/firmware/sdcclib.sh).
"""
import re
import sys
from pathlib import Path

BRANCH = re.compile(r"^(sjmp|ljmp|ajmp|jz|jnz|jc|jnc|jb|jnb|jbc|cjne|djnz)\b")
COND_LAST = {"jz", "jnz", "jc", "jnc"}           # target is the last operand for all
CALL = re.compile(r"^(lcall|acall)\s+(\S+)")
# one level of self-recursion allowed (see docstring)
# Callees with no assembly in the build, with their stack cost from the SDCC 4.5.0 sources:
FIXED = {
    "sdcc_atomic_maybe_rollback": 3,  # device/lib/mcs51/__sdcc_atomic_maybe_rollback.s: 3 pushes
    "0xff00": 0,                      # isp_jump(): ljmp into the bootloader, never returns
}
ALLOWED_RECURSION = {}  # none: the engine replays overload taps in a loop


def parse(asmdirs):
    """Functions from the asm dirs in order; the first definition of a name wins, as at
    link time (the image's own objects before the library defaults)."""
    funcs = {}
    for d in asmdirs:
        found = parse_dir(d)
        for name, body in found.items():
            funcs.setdefault(name, body)
    return funcs


def parse_dir(asmdir):
    funcs = {}
    for f in sorted(Path(asmdir).glob("*.asm")):
        cur, body = None, []
        for raw in f.read_text().splitlines():
            line = raw.split(";", 1)[0].rstrip()
            if not line.strip():
                continue
            m = re.match(r"^(\w+):\s*$", line) or re.match(r"^(\d+\$):\s*$", line.strip())
            if m and not line.startswith((" ", "\t")):
                name = m.group(1)
                if not re.match(r"^\d+\$$", name):
                    if name.startswith("_") and not name.startswith("__str") and cur != name:
                        if cur:
                            funcs[cur] = body
                        cur, body = name, []
                        continue
                body.append(("label", name))
                continue
            if cur and line.startswith((" ", "\t")):
                body.append(("ins", line.strip()))
        if cur:
            funcs[cur] = body
    return funcs


def analyze(name, body):
    """Return (max local depth excluding calls, [(call target, depth at call)])."""
    labels = {b[1]: i for i, b in enumerate(body) if b[0] == "label"}
    depth = {0: 0}
    work = [0]
    calls, maxd = [], 0
    last_add = None
    while work:
        i = work.pop()
        d = depth[i]
        while i < len(body):
            kind, txt = body[i]
            nxt = [i + 1]
            if kind == "ins":
                op = txt.split()[0]
                args = txt[len(op):].strip()
                if op == "push":
                    d += 1
                elif op == "pop":
                    d -= 1
                elif op == "inc" and args == "sp":
                    d += 1
                elif op == "dec" and args == "sp":
                    d -= 1
                elif op == "add" and args.startswith("a,#"):
                    last_add = args[3:]
                elif op == "mov" and args == "sp,a" and last_add is not None:
                    v = int(eval(last_add.replace("0x", "0x"), {}, {})) & 0xFF
                    d += v if v < 128 else v - 256
                elif op == "mov" and args.startswith("sp,") and args != "sp,a":
                    if args not in ("sp,_bp",):
                        raise SystemExit(f"{name}: cannot bound `{txt}`")
                    d = 0  # restore to frame base (after the pushes of the prologue)
                m = CALL.match(txt)
                if m:
                    calls.append((m.group(2), d + 2))
                if op in ("ret", "reti"):
                    nxt = []
                elif op in ("jmp",) and "@a+dptr" in args:
                    nxt = []  # switch table: its targets are labels reached below
                    for lab, j in labels.items():
                        if j > i and j not in depth:
                            depth[j] = d
                            work.append(j)
                elif BRANCH.match(txt):
                    target = args.split(",")[-1].strip()
                    if target in labels:
                        j = labels[target]
                        if j in depth and depth[j] != d:
                            raise SystemExit(f"{name}: stack mismatch at {target}")
                        if j not in depth:
                            depth[j] = d
                            work.append(j)
                    elif op in ("ljmp", "ajmp", "sjmp") and not target.endswith("$"):
                        calls.append((target, d))  # tail jump into another function
                    if op in ("sjmp", "ljmp", "ajmp"):
                        nxt = []
                if op not in ("add",):
                    last_add = None if op != "mov" or args != "sp,a" else last_add
            maxd = max(maxd, d)
            if not nxt:
                break
            i = nxt[0]
            if i < len(body):
                if i in depth and depth[i] != d:
                    raise SystemExit(f"{name}: stack mismatch falling into {body[i]}")
                if i in depth and body[i][0] == "label" and i != nxt[0]:
                    break
                depth.setdefault(i, d)
    return maxd, calls


def main():
    avail, asmdirs = int(sys.argv[1]), sys.argv[2:]
    funcs = parse(asmdirs)
    info = {n: analyze(n, b) for n, b in funcs.items()}
    memo = {}
    chain = {}

    def worst(n, active=()):
        if n in FIXED:
            return FIXED[n]
        if n not in info:
            raise SystemExit(f"no assembly for {n} (called from {active[-1] if active else '?'})")
        if active.count(n) > ALLOWED_RECURSION.get(n, 0):
            if n in ALLOWED_RECURSION:
                # process_descriptor recurses only for an overload's tap action, and
                # tools/keyd-oracle/export.c rejects an overload whose action is itself an
                # overload: the inner call can never recurse again.
                return 0
            raise SystemExit(f"recursion through {n}: {' -> '.join(active + (n,))}")
        key = (n, active.count(n))
        if key in memo:
            return memo[key]
        local, calls = info[n]
        w, via = local, None
        for t, d in calls:
            v = d + worst(t, active + (n,))
            if v > w:
                w, via = v, t
        memo[key] = w
        chain[key] = via
        return w

    def path(n):
        out, seen = [n], [n]
        while True:
            via = chain.get((out[-1], seen.count(out[-1]) - 1))
            if not via:
                return " -> ".join(out)
            out.append(via)
            seen.append(via)

    main_w = worst("_main")
    isrs = sorted(n for n in funcs if n.endswith("_interrupt_handler"))
    isr_w = {n: worst(n) + 2 for n in isrs}  # +2: the return address the interrupt pushes
    top = max(isr_w.values())
    print(f"main loop worst case: {main_w} bytes\n  via {path('_main')}")
    for n, w in sorted(isr_w.items(), key=lambda x: -x[1])[:4]:
        print(f"  ISR {n}: {w}\n    via {path(n)}")
    total = main_w + top
    print(f"worst case main + deepest ISR: {total} of {avail} bytes ({avail - total} spare)")
    return 0 if total <= avail else 1


if __name__ == "__main__":
    sys.exit(main())
