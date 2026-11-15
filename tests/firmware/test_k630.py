#!/usr/bin/env python3
"""Simulator tests of the K630 firmware image: escape hatches, Fn layers, resources.

Runs the release image that would be flashed (build/smk/redragon-k630_default_smk.hex)
in smk's patched uCsim. Static checks (no flash writes, memory map) run on the same image.

    python3 -m unittest discover -s tests/firmware -v
"""
import os
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
        p = subprocess.run([str(ROOT / "tools/bin/keyd-oracle"), str(ROOT / os.environ.get("K630_CONFIG", "keymap/rynsf.conf")), f.name],
                           capture_output=True, text=True, check=True)
    return [tuple(l.split()[1:3]) for l in p.stdout.splitlines() if l.strip()]


def regs(sess):
    out = sess.cmd("info registers")
    acc = re.search(r"ACC=\s*0x([0-9a-fA-F]{2})", out)
    b = re.search(r"\bB=\s*0x([0-9a-fA-F]{2})", out)
    return (int(acc.group(1), 16) if acc else None, int(b.group(1), 16) if b else None)


def clocks_up(sess):
    """At the ISP jump the chip must already run as the bootloader's ISP code expects:
    LDO on (REGCON.REGEN), PLL on and selected (PLLCON PLLON|PLLFS), CPU on the fast clock
    (CLKCON HFON|FS). Without the PLL the bootloader's USB never comes up (seen on the real
    keyboard). The simulator does not model that dependency, so it is asserted here."""
    regcon, pllcon, clkcon = sess.get_sfr(0x8F), sess.get_sfr(0xBC), sess.get_sfr(0xB2)
    return (regcon & 0x01, pllcon & 0x03, clkcon & 0x0C) == (0x01, 0x03, 0x0C)


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
        self.assertTrue(clocks_up(s), "LDO + PLL must be running for the bootloader's USB")
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
        self.assertTrue(clocks_up(s), "LDO + PLL must be running for the bootloader's USB")


class TestBootEscape(K630Case):
    def test_fn1_held_at_power_up_goes_to_isp(self):
        s = self.s
        s.set_pin(P5, 0xFF & ~(1 << 4))                  # FN1 pulls row 4 (P5.4) low
        self.assertEqual(self.boot_until(ISP, s._a("kb_update")), ISP)
        self.assertEqual(regs(s), (0x5A, 0xA5))
        self.assertTrue(clocks_up(s), "LDO + PLL must be running for the bootloader's USB")

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


# --- backlight and Caps Lock ------------------------------------------------------------
PWM24DUTY2 = None  # column 0 (Caps Lock's column) duty register, resolved from the header


def col0_duty_xram():
    h = (ROOT / "third_party/smk/src/sino51lib/sh68f90/sh68f90.h").read_text()
    lo = int(re.search(r"SFRX\(PWM24DUTY2L,\s*(0x[0-9a-fA-F]+)\)", h).group(1), 16)
    hi = int(re.search(r"SFRX\(PWM24DUTY2H,\s*(0x[0-9a-fA-F]+)\)", h).group(1), 16)
    return lo, hi


LED_DUTY = lambda level: [0, 15, 38, 80, 150, 290][level]  # backlight.c led_duty[], 0 = dark
FULL = 5


class TestBacklight(K630Case):
    def setUp(self):
        super().setUp()
        self.s.boot_configured()
        self.on, self.level = self.s._a("k630_backlight_on"), self.s._a("k630_backlight_level")

    def state(self):
        return self.s.get_xram(self.on, 1)[0], self.s.get_xram(self.level, 1)[0]

    def test_defaults_on_at_full_brightness(self):
        self.assertEqual(self.state(), (1, 5))

    def test_fn2_combos(self):
        s = self.s
        s.play("FN2 down\n0 down\n0 up\nFN2 up\n")
        self.assertEqual(self.state(), (0, 5), "FN2 + 0 turns it off")
        s.play("FN2 down\n0 down\n0 up\nFN2 up\n")
        self.assertEqual(self.state(), (1, 5), "and on again")
        s.play("FN2 down\n" + "- down\n- up\n" * 7 + "FN2 up\n")
        self.assertEqual(self.state(), (1, 1), "FN2 + - dims, stops at the lowest level")
        s.play("FN2 down\n= down\n= up\n= down\n= up\nFN2 up\n")
        self.assertEqual(self.state(), (1, 3), "FN2 + = brightens")
        self.assertEqual(s.decode(), [], "backlight combos send nothing to the host")

    def caps_column_duties(self, caps, on):
        """Run LED subframes; return the Caps Lock column's duty on the Caps row and on
        another row (the subframe leaves the active row's P6 bit low)."""
        s = self.s
        s.cmd("set mem xram 0x%x 0x%02x" % (self.on, 1 if on else 0))
        ks = s._a("keyboard_state")
        s.cmd("set mem xram 0x%x 0x%02x" % (ks, 0x02 if caps else 0x00))
        lo, hi = col0_duty_xram()
        post = s._a("indicators_post_update")
        s.scan_isr(True)
        s.brk(post)
        seen = {}
        for _ in range(40):
            s.run()
            p6 = s.get_sfr(0xC0)
            rows = [r for r in range(5) if not p6 & (1 << (r + 1))]
            if rows:
                l, h = s.get_xram(lo, 1)[0], s.get_xram(hi, 1)[0]
                seen[rows[0]] = l | h << 8
            if 2 in seen and any(r != 2 for r in seen):
                break
        s.cmd("delete")
        s.scan_isr(False)
        other = next((seen[r] for r in seen if r != 2), None)
        return seen.get(2), other

    def test_caps_lock_lights_only_its_key_when_backlight_off(self):
        caps_row, other = self.caps_column_duties(caps=True, on=False)
        self.assertEqual(caps_row, LED_DUTY(FULL), "Caps Lock key lit")
        self.assertEqual(other, LED_DUTY(0), "every other key dark")

    def test_caps_lock_darkens_only_its_key_when_backlight_on(self):
        caps_row, other = self.caps_column_duties(caps=True, on=True)
        self.assertEqual(caps_row, LED_DUTY(0), "Caps Lock key dark")
        self.assertEqual(other, LED_DUTY(FULL), "every other key lit")

    def test_no_caps_backlight_on_lights_everything(self):
        caps_row, other = self.caps_column_duties(caps=False, on=True)
        self.assertEqual((caps_row, other), (LED_DUTY(FULL), LED_DUTY(FULL)))

    def test_column_pins_return_to_the_matrix_scan(self):
        """The LED phase makes the column pins PWM inputs; every scan must get them back as
        outputs, or keys stop working. A pin-level key press after LED phases proves it."""
        s = self.s
        s.scan_isr(True)
        s.loop(30)                                   # many LED subframes
        s.scan_isr(False)
        self.assertEqual([tuple(e) for e in s.play("a down\n20ms\na up\n", direct=False)],
                         oracle("a down\n20ms\na up\n"))

    def test_every_column_channel_is_pwm_enabled(self):
        """Every LED column channel of the stock grid under PWM (stock 0x8A)."""
        s = self.s
        s.scan_isr(True)
        s.loop(10)                                   # main loop: PWM re-enabled after each tick
        s.scan_isr(False)
        h = (ROOT / "third_party/smk/src/sino51lib/sh68f90/sh68f90.h").read_text()
        # the 14 key columns + the stock grid's extra LED columns (20-23, 40-42)
        for ch in "00 01 02 03 04 05 10 11 12 13 14 15 20 21 22 23 24 25 40 41 42".split():
            m = re.search(r"SFR(X?)\(PWM%sCON,\s*(0x[0-9a-fA-F]+)\)" % ch, h)
            a = int(m.group(2), 16)
            v = s.get_xram(a, 1)[0] if m.group(1) else s.get_sfr(a)
            self.assertEqual(v & 0x8A, 0x8A, "PWM%sCON" % ch)

    def test_led_rows_off_and_pwm_running_during_the_scan(self):
        """During every matrix scan all LED rows are off (else the last row is lit at full
        power by the high column pins: Caps Lock alone lit the whole board), and the PWM
        counters keep running (MODE_ENABLE set) with the pins released (SS clear), as the
        stock firmware's scan phase (0x82)."""
        s = self.s
        s.cmd("set mem xram 0x%x 0x02" % s._a("keyboard_state"))   # Caps Lock on, backlight on
        h = (ROOT / "third_party/smk/src/sino51lib/sh68f90/sh68f90.h").read_text()
        rr = s._a("user_matrix_read_rows")
        s.scan_isr(True)
        s.loop(5)
        s.brk(rr)
        for _ in range(30):
            s.run()
            self.assertEqual(s.get_sfr(0xC0) & 0x3F, 0x3F, "all LED rows off during the scan")
            for ch in "00 01 02 03 04 05 10 11 12 13 14 15 20 21 22 23 24 25 40 41 42".split():
                m = re.search(r"SFR(X?)\(PWM%sCON,\s*(0x[0-9a-fA-F]+)\)" % ch, h)
                a = int(m.group(2), 16)
                v = s.get_xram(a, 1)[0] if m.group(1) else s.get_sfr(a)
                self.assertEqual(v & 0x8A, 0x82, "PWM%sCON: counter running, pin released" % ch)
        s.cmd("delete")
        s.scan_isr(False)

    def test_pwm_period_fits_the_led_subframe(self):
        """8 PWM periods (CLK/4) per LED subframe (801 Timer2 counts at sysclk/12), so each
        subframe shows whole periods whatever the free-running counter's phase."""
        s = self.s
        h = (ROOT / "third_party/smk/src/sino51lib/sh68f90/sh68f90.h").read_text()
        for g in "0124":
            vals = []
            for half in "LH":
                m = re.search(r"SFR(X?)\(PWM%sPERD%s,\s*(0x[0-9a-fA-F]+)\)" % (g, half), h)
                a = int(m.group(2), 16)
                vals.append(s.get_xram(a, 1)[0] if m.group(1) else s.get_sfr(a))
            period = vals[0] | vals[1] << 8
            self.assertEqual(period, 300, "PWM%s period" % g)
        self.assertLess(abs(8 * 300 * 4 - 801 * 12), 16, "whole periods per subframe")

    def test_side_caps_led_held_off(self):
        """P0.3 is the side Caps LED, active low (stock 0x55AF). Held high = off, even with
        Caps Lock on. (Floating, it glowed on the real keyboard.)"""
        s = self.s
        s.cmd("set mem xram 0x%x 0x02" % s._a("keyboard_state"))   # Caps Lock on
        s.scan_isr(True); s.loop(20); s.scan_isr(False)
        self.assertTrue(s.get_sfr(0xE1) & 0x08, "P0.3 is an output (P0CR bit 3)")
        self.assertTrue(s.get_sfr(0x80) & 0x08, "P0.3 is high: LED off")


# --- remote wakeup ------------------------------------------------------------------------
class TestRemoteWakeup(K630Case):
    def setUp(self):
        super().setUp()
        self.s.boot_configured()

    def usbcon_wkup_after_keypress(self, host_enabled):
        s = self.s
        s.set_sfr(0x91, s.get_sfr(0x91) & ~0x02)
        s.set_bit("usb_remote_wakeup", host_enabled)
        s.set_bit("usb_suspended", True)
        s.key("a", True)
        s.loop(1)                           # loop() stops at kb_update's entry: run it once more
        wk = bool(s.get_sfr(0x91) & 0x02)
        s.set_bit("usb_suspended", False)   # the host resumes
        s.key("a", False)
        return wk

    def test_keypress_while_suspended_signals_resume(self):
        self.assertTrue(self.usbcon_wkup_after_keypress(True), "USBCON.WKUP set")
        self.assertEqual(self.s.decode(), [], "the waking key is not typed, and nothing sticks")

    def test_no_resume_if_host_did_not_enable_it(self):
        self.assertFalse(self.usbcon_wkup_after_keypress(False))

    def test_keys_work_normally_after_resume(self):
        self.usbcon_wkup_after_keypress(True)
        self.assertEqual([tuple(e) for e in self.s.play("a down\na up\n")], oracle("a down\na up\n"))


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
                        str(ROOT / "build/smk/sdcclib.asm.p")],  # written by sdcclib.sh
                       capture_output=True, text=True)
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
