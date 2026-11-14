#!/usr/bin/env python3
"""Simulator tests of the K630 firmware image: escape hatches, Fn layers, resources.

Runs the release image that would be flashed (build/smk/redragon-k630_default_smk.hex)
in smk's patched uCsim. Static checks (no flash writes, memory map) run on the same image.

    python3 -m unittest discover -s tests/firmware -v
"""
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from k630sim import K630Sim, FIRMWARE, ROOT, P5  # noqa: E402
from sim import Sim, get_descriptor, DESC_DEVICE  # noqa: E402

MARKER = 0x0FFC
BOOTING = [0x4B, 0x36, 0x33, 0xB0]
ISP = 0xFF00


def oracle(script):
    with tempfile.NamedTemporaryFile("w", suffix=".keys") as f:
        f.write(script)
        f.flush()
        p = subprocess.run([str(ROOT / "tools/bin/keyd-oracle"), str(ROOT / "keymap/rynsf.conf"), f.name],
                           capture_output=True, text=True, check=True)
    return [tuple(l.split()[1:3]) for l in p.stdout.splitlines() if l.strip()]


def regs(sess):
    out = sess.cmd("info registers")
    acc = re.search(r"ACC=\s*0x([0-9a-fA-F]{2})", out)
    b = re.search(r"\bB=\s*0x([0-9a-fA-F]{2})", out)
    return (int(acc.group(1), 16) if acc else None, int(b.group(1), 16) if b else None)


class K630Case(unittest.TestCase):
    def setUp(self):
        self.s = K630Sim()

    def tearDown(self):
        self.s.close()

    def pc_after_run(self, brk_addrs, max_runs=1):
        for a in brk_addrs:
            self.s.brk(a)
        out = ""
        for _ in range(max_runs):
            out = self.s.run()
        self.s.cmd("delete")
        return self.s.stopped_at(out)

    def boot_until(self, *addrs):
        """Reset and run until the first of `addrs` (e.g. ISP, or the main loop)."""
        s = self.s
        s.cmd("reset")
        s.cmd("set mem rom 0x%x 0x22" % s._a("delay_us"))
        s.cmd("set mem rom 0x%x 0x22" % s._a("delay_ms"))
        return self.pc_after_run(addrs)


# --- escape hatches ----------------------------------------------------------------------
class TestBootMarker(K630Case):
    def test_normal_boot_reaches_main_loop_and_marks_booting(self):
        at = self.boot_until(self.s._a("kb_update"), ISP)
        self.assertEqual(at, self.s._a("kb_update"))
        self.assertEqual(self.s.get_xram(MARKER, 4), BOOTING)

    def test_marker_clears_once_main_loop_is_healthy(self):
        s = self.s
        s.boot_configured()
        s.cmd("set mem xram 0x%x 0x4f 0xc3" % s._a("k630_boot_loops"))  # 49999 = HEALTHY_LOOPS - 1
        s.loop(2)
        self.assertEqual(s.get_xram(MARKER, 4), [0, 0, 0, 0])

    def test_restart_with_marker_still_booting_goes_to_isp(self):
        """A start that hung before the main loop was healthy (watchdog reset) lands in
        the ISP bootloader on the next start, with the handshake the bootloader checks."""
        s = self.s
        s.cmd("set mem xram 0x%x %s" % (MARKER, " ".join("0x%02x" % b for b in BOOTING)))
        at = self.boot_until(ISP, s._a("kb_update"))
        self.assertEqual(at, ISP)
        self.assertEqual(regs(s), (0x5A, 0xA5))
        self.assertEqual(s.get_xram(MARKER, 4), [0, 0, 0, 0], "cleared, so the next start is normal")

    def test_hang_during_boot_ends_in_isp_via_watchdog(self):
        """End to end: the firmware hangs early (before the main loop is healthy), the
        watchdog resets the chip, and the restart goes to ISP instead of hanging again."""
        s = self.s
        s.boot_configured()                              # marker = BOOTING, loops small
        s.cmd("set mem rom 0x9000 0x80 0xfe")            # SJMP $  (a hang, no watchdog kicks)
        s.cmd("pc 0x9000")
        s.brk(ISP)
        s.sock.settimeout(120)                           # 80M simulated cycles until the watchdog
        out = s.run()
        s.sock.settimeout(10)
        s.cmd("delete")
        self.assertIn("WATCHDOG timeout", s.stderr_text())
        self.assertEqual(s.stopped_at(out), ISP)
        self.assertEqual(regs(s), (0x5A, 0xA5))


class TestBootEscape(K630Case):
    def test_fn1_held_at_power_up_goes_to_isp(self):
        s = self.s
        s.set_pin(P5, 0xFF & ~(1 << 4))                  # FN1 pulls row 4 (P5.4) low
        self.assertEqual(self.boot_until(ISP, s._a("kb_update")), ISP)
        self.assertEqual(regs(s), (0x5A, 0xA5))

    def test_no_key_held_boots_normally(self):
        s = self.s
        s.set_pin(P5, 0xFF)
        self.assertEqual(self.boot_until(ISP, s._a("kb_update")), s._a("kb_update"))


class TestPllTimeout(K630Case):
    def test_pll_that_never_locks_ends_in_isp(self):
        s = self.s
        s.cmd("reset")
        s.brk(s._a("clock_init"))
        s.run()
        s.cmd("delete")
        for _ in range(40):                              # step until PLLON has been written
            s.cmd("step")
            if (s.get_sfr(0xBC) or 0) & 0x02:
                break
        s.set_sfr(0xBC, 0x00)                            # PLLSTA clear (the model sets it on any PLLON write)
        s.brk(ISP)
        s.brk(s._a("kb_update"))                         # a failure must stop too, not run forever
        out = s.run()
        s.cmd("delete")
        self.assertEqual(s.stopped_at(out), ISP)
        self.assertEqual(regs(s), (0x5A, 0xA5))


class TestUsbIdentity(unittest.TestCase):
    def setUp(self):
        self.sim = Sim(firmware=FIRMWARE, sim=str(ROOT / "tools/bin/ucsim-sh68f90"))

    def test_device_descriptor_is_stock_k630_id(self):
        desc = self.sim.reassemble(self.sim.control_in(get_descriptor(DESC_DEVICE)))
        self.assertEqual((desc[8] | desc[9] << 8, desc[10] | desc[11] << 8), (0x258A, 0x002A))

    def test_isp_report_jumps_to_bootloader(self):
        out = self.sim.trigger_isp_jump()
        self.assertEqual(self.sim.stopped_at(out), Sim.ISP_BOOTLOADER)
        self.assertEqual((self.sim.acc(out), self.sim.reg_b(out)), (0x5A, 0xA5))

    def test_wrong_isp_confirm_does_not_jump(self):
        out = self.sim.trigger_isp_jump(confirm=(0, 0), run_task=False)
        self.assertEqual(self.sim.stopped_at(out), Sim.SLED_END)


# --- Fn layers (applied before the keyd engine, like the stock keyboard + keyd today) ---
class TestFnLayers(K630Case):
    def setUp(self):
        super().setUp()
        self.s.boot_configured()

    def play(self, script):
        return [tuple(e) for e in self.s.play(script)]

    def test_fn1_translations_reach_keyd(self):
        pairs = [("esc", "grave"), ("1", "f1"), ("0", "f10"), ("-", "f11"), ("=", "f12"),
                 ("w", "up"), ("a", "left"), ("s", "down"), ("d", "right"), ("p", "sysrq"),
                 ("[", "home"), ("]", "end"), (";", "pageup"), ("'", "pagedown"),
                 (".", "insert"), ("/", "delete")]
        script = "FN1 down\n" + "".join(f"{k} down\n10ms\n{k} up\n10ms\n" for k, _ in pairs) + "FN1 up\n"
        want = oracle("".join(f"{v} down\n10ms\n{v} up\n10ms\n" for _, v in pairs))
        self.assertEqual(self.play(script), want)

    def test_fn1_released_first_does_not_stick(self):
        self.assertEqual(self.play("FN1 down\nw down\nFN1 up\nw up\n"), oracle("up down\nup up\n"))

    def test_fn1_with_unmapped_key_sends_nothing(self):
        self.assertEqual(self.play("FN1 down\nq down\nq up\nFN1 up\n"), [])

    def test_fn1_keeps_modifiers(self):
        self.assertEqual(self.play("FN1 down\nleftcontrol down\nw down\nw up\nleftcontrol up\nFN1 up\n"),
                         oracle("leftcontrol down\nup down\nup up\nleftcontrol up\n"))

    def test_fn2_tap_is_menu(self):
        self.assertEqual(self.play("FN2 down\n50ms\nFN2 up\n"), oracle("compose down\ncompose up\n"))

    def test_fn2_combo_sends_nothing_and_no_menu(self):
        self.assertEqual(self.play("FN2 down\n9 down\n9 up\nFN2 up\n"), [])

    def test_win_lock_toggles(self):
        tap = "leftmeta down\n10ms\nleftmeta up\n10ms\n"
        locked = self.play("FN1 down\nleftmeta down\nleftmeta up\nFN1 up\n" + tap)
        self.assertEqual(locked, [], "Win-lock on: the Win key sends nothing")
        unlocked = [tuple(e) for e in self.s.play("FN1 down\nleftmeta down\nleftmeta up\nFN1 up\n" + tap)]
        self.assertEqual(unlocked, oracle(tap), "Win-lock off again: Win goes through keyd")


# --- resources ----------------------------------------------------------------------------
class TestResources(K630Case):
    def test_stack_on_a_heavy_engine_path(self):
        """Nested overloads + layout switch + oneshot through the engine, driven through the
        pin-level scan (so the Timer2 scan ISR can nest on any engine frame), with the deepest
        USB ISR nested on top. Must not overflow the 8051's internal stack."""
        s = self.s
        s.boot_configured()
        s.paint_stack()
        s.play("capslock down\n50ms\nenter down\n50ms\nspace down\n50ms\nk down\nk up\n"
               "space up\nenter up\ncapslock up\n200ms\ntab down\n200ms\n1 down\n1 up\ntab up\n"
               "leftshift down\nleftshift up\nj down\nj up\nspace down\n300ms\nl down\nl up\nspace up\n", direct=False)  # pin-level: the scan ISR nests on the engine
        s.nest_usb_descriptor()
        used, avail = s.stack_highwater(), 0xFF - s.stack_base
        print(f"\n  stack high-water: {used} of {avail} bytes")
        self.assertNotIn("Stack overflow", s.stderr_text())
        self.assertLess(used, avail - 32, "keep at least 32 bytes of stack headroom")


def stack_bound():
    """Static worst case (main loop + deepest ISR) and the stack available, from the image's
    assembly (tests/firmware/stack_bound.py)."""
    build = Path(FIRMWARE).parent
    subprocess.run([str(HERE / "sdcclib.sh")], check=True, capture_output=True)
    p = subprocess.run([sys.executable, str(HERE / "stack_bound.py"), "222",
                        str(Path(FIRMWARE).with_suffix(".ihx.p")), str(build / "user.lib.p"),
                        str(build / "sdcclib.asm.p")], capture_output=True, text=True)
    m = re.search(r"worst case main \+ deepest ISR: (\d+) of (\d+)", p.stdout)
    assert m, p.stdout + p.stderr
    main = int(re.search(r"main loop worst case: (\d+)", p.stdout).group(1))
    return int(m.group(1)), int(m.group(2)), main, p.stdout


class TestImage(unittest.TestCase):
    def test_static_stack_bound_has_headroom(self):
        """Every call path, not just the ones the scripts reach: main loop worst case plus
        the deepest interrupt (they share one priority, so ISRs cannot nest)."""
        worst, avail, _, out = stack_bound()
        print("\n  " + out.strip().replace("\n", "\n  "))
        self.assertLessEqual(worst + 32, avail, "keep at least 32 bytes of stack headroom")

    def test_measured_peak_within_static_bound(self):
        """Sanity check of the analysis: what the simulator measures must never exceed it."""
        _, _, main, _ = stack_bound()
        s = K630Sim()
        try:
            s.boot_configured()
            s.brk(s._a("kb_update")); s.run(); s.cmd("delete")
            s.paint_stack()
            s.play((ROOT / "tests/firmware/deep-2-27.keys").read_text())
            used = s.stack_highwater()
        finally:
            s.close()
        self.assertLessEqual(used, main)

    def test_no_flash_write_code(self):
        p = subprocess.run([sys.executable, str(HERE / "check_no_flash_write.py"), FIRMWARE],
                           capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stdout)

    def test_memory_map(self):
        mem = Path(FIRMWARE).with_suffix(".mem").read_text()
        xram_end = int(re.search(r"EXTERNAL RAM\s+0x[0-9a-f]+\s+0x([0-9a-f]+)", mem).group(1), 16)
        rom_end = int(re.search(r"ROM/EPROM/FLASH\s+0x[0-9a-f]+\s+0x([0-9a-f]+)", mem).group(1), 16)
        self.assertLess(xram_end, MARKER, "XRAM data must stay below the boot marker")
        self.assertLess(rom_end, 0xEFFB, "image must end below the relocated reset vector")


if __name__ == "__main__":
    unittest.main()
