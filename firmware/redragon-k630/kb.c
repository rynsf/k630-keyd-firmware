// Redragon K630: key pipeline and anti-brick escape hatches.
//
//   matrix -> stock Fn layers (FN1 translation, FN2, Win-lock) -> keyd engine -> HID reports
//
// The same pipeline as a stock K630 with keyd on the computer (keyboard Fn translation, then
// keyd), moved into the keyboard. See docs/DESIGN.md and re/K630-HARDWARE.md.
#include <stdint.h>
#include <stdbool.h>
#include "kbdef.h"
#include "report.h"
#include "host.h"
#include "usb.h"
#include "isp.h"
#include "ldo.h"
#include "clock.h"
#include "user_init.h"
#include "kb.h"
#include "hidmap.h"
#include "engine/kd.h"

// ---------------------------------------------------------------------------------------
// Watchdog fallback. The stock bootloader runs on every reset and clears RSTSTAT before
// jumping here, so the reset cause is unknown. Instead a marker at the top of XRAM (above
// everything the linker places; the bootloader's normal path never touches XRAM) says
// whether the previous start got as far as a healthy main loop. A start that finds the
// marker still at BOOTING follows a hang during boot (watchdog reset), so it goes to ISP.
// Power-up leaves XRAM random: a false match needs these exact 4 bytes.
// ---------------------------------------------------------------------------------------
#define BOOT_MARKER_ADDR 0x0FFC
#define HEALTHY_LOOPS    50000u // main-loop passes before the start counts as healthy

static __xdata __at(BOOT_MARKER_ADDR) volatile uint8_t boot_marker[4];
static const __code uint8_t BOOTING[4] = {0x4B, 0x36, 0x33, 0xB0}; // "K63" 0xB0

static bool marker_is_booting(void)
{
    for (uint8_t i = 0; i < 4; i++) {
        if (boot_marker[i] != BOOTING[i]) {
            return false;
        }
    }
    return true;
}

static void marker_write(bool booting)
{
    for (uint8_t i = 0; i < 4; i++) {
        boot_marker[i] = booting ? BOOTING[i] : 0;
    }
}

// The bootloader's ISP entry (0xFF00) expects the chip already running: its own cold-start
// ISP path enables the LDO and starts the PLL first, but the entry the firmware jumps to
// does not, and USB cannot work without the PLL. (Found on the real keyboard: jumping from
// early boot left the chip in ISP mode with no USB at all.) So the early-boot exits bring
// the clocks up exactly as init() would, then jump.
static void enter_isp(void)
{
    marker_write(false); // the start after ISP mode boots normally
    ldo_init();
    clock_init(); // a PLL that never locks jumps to ISP itself (bounded wait)
    isp_jump();
}

// FN1 (c9 = P3.1) pulls row 4 (P5.4) low while held. Read before clocks, USB or anything
// else is set up, so a firmware that dies later in init can still be escaped from.
static bool fn1_held_at_power_up(void)
{
    bool held = true;

    P5CR &= (uint8_t)~_P5_4; // row: input with pull-up
    P5PCR |= _P5_4;
    P3CR |= _P3_1; // column: output low
    BOOT_ESCAPE_COL_PIN = 0;

    for (volatile uint16_t i = 0; i < 1000u; i++) { // let the row line settle
    }
    for (uint8_t n = 0; n < 32; n++) { // held only if every sample reads low
        if (BOOT_ESCAPE_ROW_PIN) {
            held = false;
        }
    }

    BOOT_ESCAPE_COL_PIN = 1;
    return held;
}

void board_early_boot(void)
{
    if (marker_is_booting()) {
        enter_isp(); // the last start hung before reaching a healthy main loop
    }
    marker_write(true);

    if (fn1_held_at_power_up()) {
        enter_isp();
    }
}

// ---------------------------------------------------------------------------------------
// Clock: USB start-of-frame, one per ms while the host drives the bus. (The SH68F90 has
// no free timer: Timer2 alternates matrix-scan and LED slots.) The clock stops while the
// bus is suspended, which only delays engine timeouts the host could not see anyway.
// ---------------------------------------------------------------------------------------
static uint16_t  last_sof;
static kd_time_t now_ms;

static kd_time_t clock_now(void)
{
    uint16_t sof;
    __critical
    {
        sof = usb_sof_ms;
    }
    now_ms += (uint16_t)(sof - last_sof);
    last_sof = sof;
    return now_ms;
}

// ---------------------------------------------------------------------------------------
// keyd engine glue
// ---------------------------------------------------------------------------------------
static kd_time_t deadline;
static bool      timer_armed;

#define TIME_GE(a, b) ((int32_t)((uint32_t)(a) - (uint32_t)(b)) >= 0)

// These run only from the main loop, one at a time, so their arguments live in static
// memory: on the 8051 every pushed argument byte is internal stack the engine needs.
static kd_time_t feed_t;
static uint8_t   feed_code, feed_pressed;

static kd_time_t feed_next;

static void engine_feed(void)
{
    feed_next   = kd_event(feed_code, feed_pressed, feed_t);
    timer_armed = feed_next > 0;
    deadline    = feed_t + feed_next;
}

// A due timeout fires first, at its own deadline, exactly as keyd's daemon loop does.
static kd_time_t timeouts_until;

static void engine_timeouts(void)
{
    while (timer_armed && TIME_GE(timeouts_until, deadline)) {
        feed_code    = 0;
        feed_pressed = 0;
        feed_t       = deadline;
        engine_feed();
    }
}

// The engine never runs inside smk's key handler and never sends reports itself: input
// events and engine outputs go through two queues, drained from kb_update(). That keeps
// the deepest engine path short, because on the 8051 every call level costs internal stack
// (~220 bytes, shared with the USB interrupt).
#define IN_Q  16 // key events from one matrix pass
#define OUT_Q 64 // engine outputs from one batch of input
struct in_ev {
    uint8_t   hid, pressed;
    kd_time_t t;
};
struct out_ev {
    uint8_t code, pressed;
};
static __xdata struct in_ev  in_q[IN_Q];
static __xdata struct out_ev out_q[OUT_Q];
static uint8_t               in_head, in_tail, out_head, out_tail;
uint8_t                      k630_queue_overflow; // non-zero: an event was dropped (tests assert 0)

static void engine_key(uint8_t hid, uint8_t pressed)
{
    const uint8_t next = (uint8_t)((in_head + 1) & (IN_Q - 1));
    if (next == in_tail) {
        k630_queue_overflow |= 1;
        return;
    }
    in_q[in_head].hid     = hid;
    in_q[in_head].pressed = pressed;
    in_q[in_head].t       = clock_now();
    in_head               = next;
}

static void engine_input(uint8_t hid, uint8_t pressed)
{
    uint8_t code;

    if (hid >= 0xE0 && hid <= 0xE7) {
        code = hidmod_to_keyd[hid - 0xE0];
    } else if (hid < HIDMAP_KEYS) {
        code = hid_to_keyd[hid];
    } else {
        return;
    }
    if (!code) {
        return;
    }

    // the queued event at in_tail: first the timeouts due before it, then the event
    timeouts_until = in_q[in_tail].t;
    engine_timeouts();
    feed_t       = in_q[in_tail].t;
    feed_code    = code;
    feed_pressed = pressed;
    engine_feed();
}

void kd_output(uint8_t code, uint8_t pressed)
{
    const uint8_t next = (uint8_t)((out_head + 1) & (OUT_Q - 1));
    if (next == out_tail) {
        k630_queue_overflow |= 2;
        return;
    }
    out_q[out_head].code    = code;
    out_q[out_head].pressed = pressed;
    out_head                = next;
}

static void send_output(uint8_t code, uint8_t pressed)
{
    const uint8_t hid = keyd_to_hid[code];

    if (hid >= 0xE0) {
        const uint8_t bit = (uint8_t)(1u << (hid - 0xE0));
        if (pressed) {
            add_mods(bit);
        } else {
            del_mods(bit);
        }
        send_keyboard_report();
        return;
    }
    if (hid) {
        if (pressed) {
            add_key(hid);
        } else {
            del_key(hid);
        }
        send_keyboard_report();
        return;
    }
    for (uint8_t i = 0; i < HIDMAP_CONSUMER; i++) {
        if (hidmap_consumer[i].code == code) {
            host_consumer_send(pressed ? hidmap_consumer[i].usage : 0);
            return;
        }
    }
    // anything else (mouse buttons, keys with no HID usage) is dropped
}

// ---------------------------------------------------------------------------------------
// Stock Fn layers (decoded from the stock firmware, cross-checked with the manual).
// FN1: translates a fixed set of keys; any other non-modifier key sends nothing.
// FN2: tap = Menu; while held, non-modifier keys send nothing (they are the lighting
//      combos, Phase 4). Modifiers always pass through, as in the stock firmware.
// FN1 + LWin toggles Win-lock (not saved), which then drops both GUI keys.
// What a key was pressed as is remembered, so releasing Fn first cannot leave it stuck.
// ---------------------------------------------------------------------------------------
static const __code uint8_t FN1_FROM[] = {
    KC_ESC, KC_1, KC_2, KC_3, KC_4, KC_5, KC_6, KC_7, KC_8, KC_9, KC_0, KC_MINS, KC_EQL,
    KC_W, KC_A, KC_S, KC_D, KC_P, KC_LBRC, KC_RBRC, KC_SCLN, KC_QUOT, KC_DOT, KC_SLSH,
};
static const __code uint8_t FN1_TO[] = {
    KC_GRV, KC_F1, KC_F2, KC_F3, KC_F4, KC_F5, KC_F6, KC_F7, KC_F8, KC_F9, KC_F10, KC_F11, KC_F12,
    KC_UP, KC_LEFT, KC_DOWN, KC_RGHT, KC_PSCR, KC_HOME, KC_END, KC_PGUP, KC_PGDN, KC_INS, KC_DEL,
};
_Static_assert(sizeof(FN1_FROM) == sizeof(FN1_TO), "FN1 table");

static __xdata uint8_t pressed_as[0xE8]; // by base HID usage; 0 = sent nothing
static bool            fn1, fn2, fn2_combo, win_lock;

static uint8_t fn1_translate(uint8_t hid)
{
    for (uint8_t i = 0; i < sizeof(FN1_FROM); i++) {
        if (FN1_FROM[i] == hid) {
            return FN1_TO[i];
        }
    }
    return 0;
}

static uint8_t key_down_as(uint8_t hid)
{
    const bool is_mod = hid >= 0xE0;
    const bool is_gui = hid == KC_LGUI || hid == KC_RGUI;

    if (fn1 && hid == KC_LGUI) {
        win_lock = !win_lock;
        return 0;
    }
    if (is_mod) {
        return (win_lock && is_gui) ? 0 : hid;
    }
    if (fn1) {
        return fn1_translate(hid);
    }
    if (fn2) {
        fn2_combo = true; // lighting combos: not implemented yet (Phase 4)
        return 0;
    }
    return hid;
}

bool kb_process_record(uint16_t keycode, bool key_pressed)
{
    if (keycode == K630_FN1) {
        fn1 = key_pressed;
        return false;
    }
    if (keycode == K630_FN2) {
        if (key_pressed) {
            fn2       = true;
            fn2_combo = false;
        } else {
            fn2 = false;
            if (!fn2_combo) { // tapped alone: Menu
                engine_key(KC_APP, 1);
                engine_key(KC_APP, 0);
            }
        }
        return false;
    }
    if (keycode >= sizeof(pressed_as)) {
        return false;
    }

    const uint8_t hid = (uint8_t)keycode;
    if (key_pressed) {
        const uint8_t as = key_down_as(hid);
        pressed_as[hid]  = as;
        if (as) {
            engine_key(as, 1);
        }
    } else {
        const uint8_t as = pressed_as[hid];
        pressed_as[hid]  = 0;
        if (as) {
            engine_key(as, 0);
        }
    }
    return false; // nothing for smk's own keycode handling
}

// ---------------------------------------------------------------------------------------
// smk hooks
// ---------------------------------------------------------------------------------------
uint16_t k630_boot_loops; // global so the simulator tests can find it

void kb_init(void)
{
    kd_init();
}

void kb_update(void)
{
    if (k630_boot_loops < HEALTHY_LOOPS) {
        if (++k630_boot_loops == HEALTHY_LOOPS) {
            marker_write(false); // this start is healthy: a later watchdog reset just reboots
        }
    }
    // queued keys first, in order: each fires only the timeouts due before its own time
    while (in_tail != in_head) {
        engine_input(in_q[in_tail].hid, in_q[in_tail].pressed);
        in_tail = (uint8_t)((in_tail + 1) & (IN_Q - 1));
    }
    timeouts_until = clock_now();
    engine_timeouts();
    while (out_tail != out_head) {
        send_output(out_q[out_tail].code, out_q[out_tail].pressed);
        out_tail = (uint8_t)((out_tail + 1) & (OUT_Q - 1));
    }
}

void kb_send_report(__xdata report_keyboard_t *report)
{
    usb_send_report(report);
}

void kb_send_nkro(__xdata report_nkro_t *report)
{
    usb_send_nkro(report);
}

void kb_send_extra(__xdata report_extra_t *report)
{
    usb_send_extra(report);
}
