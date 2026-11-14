"""The Redragon K630 board, around the real firmware image running in smk's patched uCsim.

Reuses smk's simulator session (third_party/smk/tests/devices.py) and adds:
  - the K630 key matrix (column pins as in firmware/redragon-k630/kbdef.h),
  - a controllable clock (the firmware's ms clock is the USB SOF counter `usb_sof_ms`),
  - decoding of the endpoint reports (6KRO on EP1, NKRO / consumer on EP2) back into keyd
    key events, so the firmware's output can be compared with keyd itself.
"""
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "third_party/smk/tests"))
sys.path.insert(0, str(ROOT / "tools"))

from devices import Air60Sim, P1, P2, P3, P5, P7  # noqa: E402
from sim import find_sim  # noqa: E402

FIRMWARE = os.environ.get("K630_FIRMWARE", str(ROOT / "build/smk/redragon-k630_default_smk.hex"))
UCSIM = os.environ.get("SMK_UCSIM", str(ROOT / "tools/bin/ucsim-sh68f90"))

# K630 wiring: rows P7.1-3, P5.3-4; columns P1.4-5, P2.0-5, P3.0-5
COL_PIN = {0: (P1, 4), 1: (P1, 5), 2: (P2, 0), 3: (P2, 1), 4: (P2, 2), 5: (P2, 3), 6: (P2, 4),
           7: (P2, 5), 8: (P3, 0), 9: (P3, 1), 10: (P3, 2), 11: (P3, 3), 12: (P3, 4), 13: (P3, 5)}
ROW_PIN = {0: (P7, 1), 1: (P7, 2), 2: (P7, 3), 3: (P5, 3), 4: (P5, 4)}

# keyd names by matrix position (firmware/redragon-k630/layouts/default/layout.c)
LAYOUT = [
    "esc 1 2 3 4 5 6 7 8 9 0 - = backspace".split(),
    "tab q w e r t y u i o p [ ] \\".split(),
    "capslock a s d f g h j k l ; ' NONE enter".split(),
    "leftshift z x c v b n m , . / NONE rightshift NONE".split(),
    "leftcontrol leftmeta leftalt NONE NONE space NONE NONE rightalt FN1 FN2 NONE rightcontrol NONE".split(),
]
POS = {name: (c, r) for r, row in enumerate(LAYOUT) for c, name in enumerate(row) if name != "NONE"}


def _keyd_names():
    """keyd code -> name, from keyd's own keys.h / keys.c (the oracle prints these)."""
    src = ROOT / "third_party/keyd/src"
    num = {m.group(1): int(m.group(2)) for m in
           re.finditer(r"#define\s+(KEYD_\w+)\s+(\d+)", (src / "keys.h").read_text())}
    names = {}
    for m in re.finditer(r'\[(KEYD_\w+)\]\s*=\s*\{\s*"([^"]+)"', (src / "keys.c").read_text()):
        if m.group(1) in num:
            names[num[m.group(1)]] = m.group(2).encode().decode("unicode_escape")  # C string
    return names


KEYD_NAME = _keyd_names()
KEYD_CODE = {v: k for k, v in KEYD_NAME.items()}


def _hid_tables():
    import gen_hidmap as g
    hid_to_code = {u: c for u, c in enumerate(g.HID_KEYBOARD) if c}
    hid_to_code.update(g.MODS)
    consumer_to_code = {u: c for c, u in g.CONSUMER.items()}
    return hid_to_code, consumer_to_code


HID_TO_CODE, CONSUMER_TO_CODE = _hid_tables()


class K630Matrix:
    def __init__(self):
        self.pressed = set()

    def inject(self, sess):
        cache, low = {}, set()
        for (c, r) in self.pressed:
            sfr, bit = COL_PIN[c]
            v = cache.get(sfr)
            if v is None:
                v = cache[sfr] = sess.get_sfr(sfr) or 0
            if not v & (1 << bit):
                low.add(r)
        p7, p5 = 0xFF, 0xFF
        for r in low:
            port, bit = ROW_PIN[r]
            if port == P7:
                p7 &= ~(1 << bit)
            else:
                p5 &= ~(1 << bit)
        sess.set_pin(P7, p7)
        sess.set_pin(P5, p5)


class K630Sim(Air60Sim):
    def __init__(self, firmware=FIRMWARE, sim=UCSIM):
        super().__init__(firmware, sim if Path(sim).exists() else find_sim())
        self.matrix = K630Matrix()
        self.sof = 0
        self._seen = 0          # stderr lines already decoded
        self._mods = 0
        self._keys = set()
        self._consumer = 0
        self.events = []        # decoded (keyd name, 'down'|'up')

    def close(self):
        """Stop the simulator outright. (smk's session sends `quit`, but uCsim only closes
        that console connection and keeps running, so every close waited out a 3 s timeout.)"""
        for step in (self.sock.close, self.proc.kill):
            try:
                step()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=5)
        except Exception:
            pass
        try:
            self.proc.stderr.close()
        except Exception:
            pass
        if self._serr_thread.is_alive():
            self._serr_thread.join(timeout=1)

    # --- boot / clock ------------------------------------------------------------------
    def boot_configured(self):
        self.boot(usb=True)
        self.mark_usb_configured()
        self.set_ms(0)
        self.scan_isr(False)

    IE, ET2 = 0xA8, 0x01  # IEN0.ET2 is bit 0 on the SH68F90

    def scan_isr(self, on):
        """The Timer2 tick runs the matrix scan. The fast path writes matrix[] itself, so the
        scan must be off then, or it overwrites matrix[] with the idle pins."""
        ie = self.get_sfr(self.IE)
        self.set_sfr(self.IE, (ie | self.ET2) if on else (ie & ~self.ET2))
        self._isr_on = on

    def set_ms(self, ms):
        self.sof = ms & 0xFFFF
        a = self._a("usb_sof_ms")
        self.cmd("set mem xram 0x%x 0x%02x 0x%02x" % (a, self.sof & 0xFF, self.sof >> 8))

    def advance(self, ms):
        self.set_ms(self.sof + ms)
        self.loop(2)

    # --- running ----------------------------------------------------------------------
    _isr_on = False

    def loop(self, n=1):
        """Run n main-loop passes (stopping at kb_update each time)."""
        self.brk(self._a("kb_update"))
        for _ in range(n):
            self.run()
        self.cmd("delete")

    def scan(self, scans=2):
        """Let the real matrix scan see the staged keys, then let matrix_task process them."""
        rr, ku = self._a("user_matrix_read_rows"), self._a("kb_update")
        self.brk(rr)
        self.brk(ku)
        reads, after = 0, 0
        while after < 2:
            out = self.run()
            at = self.stopped_at(out)
            if at == rr:
                self.matrix.inject(self)
                reads += 1
            elif at == ku and reads >= 28 * scans:
                after += 1
        self.cmd("delete")

    def set_matrix_direct(self):
        """Fast path: write the scan result straight into matrix[] (skips the pin-level
        scan, keeps matrix_task -> kb_process_record -> engine -> USB)."""
        cols = [0] * 14
        for (c, r) in self.matrix.pressed:
            cols[c] |= 1 << r
        self.cmd("set mem xram 0x%x " % self._a("matrix") + " ".join("0x%02x" % v for v in cols))
        self.cmd("set mem xram 0x%x 0x01" % self._a("matrix_updated"))
        self.loop(2)

    def key(self, name, down, direct=True):
        pos = POS[name]
        (self.matrix.pressed.add if down else self.matrix.pressed.discard)(pos)
        if direct:
            self.set_matrix_direct()
        else:
            # The scan ISR runs only while its row reads are served from the matrix here;
            # otherwise (e.g. during clock advances) a scan would read stale pin levels.
            # With it off, matrix[] keeps the last real scan, as for keys held still.
            self.scan_isr(True)
            self.scan()
            self.scan_isr(False)

    # --- output decoding ----------------------------------------------------------------
    def _diff(self, mods, keys):
        for bit in range(8):
            m = 1 << bit
            if (mods ^ self._mods) & m:
                self.events.append((KEYD_NAME[HID_TO_CODE[0xE0 + bit]], "down" if mods & m else "up"))
        for u in sorted(self._keys - keys):
            self.events.append((KEYD_NAME[HID_TO_CODE[u]], "up"))
        for u in sorted(keys - self._keys):
            self.events.append((KEYD_NAME[HID_TO_CODE[u]], "down"))
        self._mods, self._keys = mods, keys

    def decode(self):
        """Turn new endpoint reports into keyd events (self.events); returns the list."""
        lines = self.stderr_text().splitlines()
        for line in lines[self._seen:]:
            m = re.match(r"\[SIE\] EP([12]) IN \d+ bytes:((?: [0-9a-f]{2})*)", line)
            if not m:
                continue
            b = [int(x, 16) for x in m.group(2).split()]
            if m.group(1) == "1":                       # 6KRO: mods, 0, keys[6]
                self._diff(b[0], {k for k in b[2:8] if k})
            elif b and b[0] == 6:                        # NKRO: id, mods, bitmap
                keys = {i * 8 + j for i, v in enumerate(b[2:]) for j in range(8) if v >> j & 1}
                self._diff(b[1], keys)
            elif b and b[0] == 2:                        # consumer: id, usage16
                usage = b[1] | b[2] << 8
                if usage:
                    self.events.append((KEYD_NAME[CONSUMER_TO_CODE[usage]], "down"))
                elif self._consumer:
                    self.events.append((KEYD_NAME[CONSUMER_TO_CODE[self._consumer]], "up"))
                self._consumer = usage
        self._seen = len(lines)
        return self.events

    # --- keyd .keys scripts -----------------------------------------------------------
    def play(self, script_text, direct=True):
        """Replay a tests/scripts-style script ("<key> down|up", "<n>ms"); returns the
        decoded output, then lets every pending timeout expire (as the oracle does)."""
        for line in script_text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.endswith("ms"):
                self.advance(int(line[:-2]))
            else:
                name, state = line.rsplit(" ", 1)
                self.key(name, state == "down", direct)
        for _ in range(4):               # oracle runs timeouts to t+100000
            self.advance(30000)
        return self.decode()
