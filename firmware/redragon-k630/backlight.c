// K630 backlight: one mode, every key at one brightness, on or off.
//
// LED circuit (from the stock firmware's driver, re/K630-HARDWARE.md): rows P6.1-P6.5
// active low, one PWM channel per key column (the same 14 channels as the Z11). As in the
// stock firmware: every column channel is under PWM (0x8A) during an LED phase, the column
// pins are inputs without pull-up so the PWM drives them, duty1 0, duty2 = brightness
// (higher = brighter, 0 = dark). The PWM counters are never stopped: for the matrix scan
// only the pin output (SS) is switched off (stock phase 0 writes 0x82), and the LED rows
// are switched off (user_matrix_sinks_off). Stopping the counters every subframe, and
// leaving the last LED row on during the scan with every column driven high, made "duty
// 0" light up and hid the brightness steps.
//
// The PWM period (user_init.c) is 1/8 of an LED subframe (smk systick: 801 Timer2 counts =
// 9612 sysclk; 8 x 300 PWM counts x 4 = 9600 sysclk), so every subframe shows whole PWM
// periods and the brightness does not depend on where the free-running counter is.
//
// Caps Lock is shown on the Caps Lock key itself, as the inverse of the backlight: with
// the backlight off it is the only lit key, with the backlight on it is the only dark one.
// The side Caps LED (P0.3, active low) is held off by user_init.c.
//
// Nothing is saved (no flash writes): every power-up starts with the backlight off (FN2 + 0
// turns it on) at full brightness. While
// the host has the USB bus suspended, everything is dark.
#include "indicators.h"
#include "sh68f90.h"
#include "kbdef.h"
#include "gpio.h"
#include "pwm.h"
#include "usb.h"
#include "backlight.h"

// The stock firmware drives a 6 x 21 LED grid (it is a generic full-size build): rows
// P6.0-P6.5, columns = the 14 key-column channels + PWM20-23 + PWM40-42. Not every K630
// LED sits at its key's matrix position (key 4's LED is on one of the extra lines: dark
// with only the 14 x 5 key grid), so "all on" drives the whole stock grid, as stock does.
#define LED_ROWS 6 // P6.0 .. P6.5; key row r is LED row r + 1
// duty2 per brightness level, out of the period 300 (user_init.c): roughly doubling,
// so each step is visible (5%, 13%, 27%, 50%, 97%)
static const uint16_t __code led_duty[BACKLIGHT_LEVELS] = {15, 38, 80, 150, 290};
#define COL_P1        (uint8_t)(KB_C0_P1_4 | KB_C1_P1_5)
#define COL_P2        (uint8_t)(KB_C2_P2_0 | KB_C3_P2_1 | KB_C4_P2_2 | KB_C5_P2_3 | KB_C6_P2_4 | KB_C7_P2_5)
#define COL_P3        (uint8_t)(KB_C8_P3_0 | KB_C9_P3_1 | KB_C10_P3_2 | KB_C11_P3_3 | KB_C12_P3_4 | KB_C13_P3_5)
#define XCOL_P1       (uint8_t)(_P1_0 | _P1_1 | _P1_2 | _P1_3) // stock LED columns 14-17
#define XCOL_P5       (uint8_t)(_P5_0 | _P5_1 | _P5_2)         // stock LED columns 18-20
#define PWM_CON_COL   0x8A // stock: MODE_ENABLE | SS | CLK/4, on every column channel
#define PWM_CON_IDLE  0x82 // stock phase 0: MODE_ENABLE | CLK/4, counter runs, pin released

#define LED_ALL_ROWS (uint8_t)(_P6_0 | LED_R0_P6_1 | LED_R1_P6_2 | LED_R2_P6_3 | LED_R3_P6_4 | LED_R4_P6_5)

#define CAPS_ROW 3 // LED row of key row 2 (P6.3)
#define CAPS_COL 0


uint8_t k630_backlight_on;    // globals so the simulator tests can read them
uint8_t k630_backlight_level; // 1..BACKLIGHT_LEVELS

static uint8_t led_row;

void backlight_toggle(void)
{
    k630_backlight_on = !k630_backlight_on;
}

void backlight_brighter(void)
{
    if (k630_backlight_level < BACKLIGHT_LEVELS) {
        k630_backlight_level++;
    }
}

void backlight_dimmer(void)
{
    if (k630_backlight_level > 1) {
        k630_backlight_level--;
    }
}

void indicators_start()
{
    led_row              = 0;
    k630_backlight_on    = 0; // off by default
    k630_backlight_level = BACKLIGHT_LEVELS;
    indicators_pwm_enable();
}

void indicators_pre_update()
{
    GPIO_HIGH(6, LED_ALL_ROWS); // all LED rows off while the columns change
    indicators_pwm_disable();
    // hand the column pins to the PWM block (stock 0x427A); user_matrix_scan_pre() takes
    // them back before every matrix scan
    GPIO_INPUT(1, (uint8_t)(COL_P1 | XCOL_P1));
    GPIO_PULLUP_OFF(1, (uint8_t)(COL_P1 | XCOL_P1));
    GPIO_INPUT(5, XCOL_P5);
    GPIO_PULLUP_OFF(5, XCOL_P5);
    GPIO_INPUT(2, COL_P2);
    GPIO_PULLUP_OFF(2, COL_P2);
    GPIO_INPUT(3, COL_P3);
    GPIO_PULLUP_OFF(3, COL_P3);
}

static void set_all_columns(uint16_t duty)
{
    SET_PWM_DUTY_2(LED_PWM_C0, duty);
    SET_PWM_DUTY_2(LED_PWM_C1, duty);
    SET_PWM_DUTY_2(LED_PWM_C2, duty);
    SET_PWM_DUTY_2(LED_PWM_C3, duty);
    SET_PWM_DUTY_2(LED_PWM_C4, duty);
    SET_PWM_DUTY_2(LED_PWM_C5, duty);
    SET_PWM_DUTY_2(LED_PWM_C6, duty);
    SET_PWM_DUTY_2(LED_PWM_C7, duty);
    SET_PWM_DUTY_2(LED_PWM_C8, duty);
    SET_PWM_DUTY_2(LED_PWM_C9, duty);
    SET_PWM_DUTY_2(LED_PWM_C10, duty);
    SET_PWM_DUTY_2(LED_PWM_C11, duty);
    SET_PWM_DUTY_2(LED_PWM_C12, duty);
    SET_PWM_DUTY_2(LED_PWM_C13, duty);
    SET_PWM_DUTY_2(PWM23, duty); // stock LED columns 14-17
    SET_PWM_DUTY_2(PWM22, duty);
    SET_PWM_DUTY_2(PWM21, duty);
    SET_PWM_DUTY_2(PWM20, duty);
    SET_PWM_DUTY_2(PWM40, duty); // stock LED columns 18-20
    SET_PWM_DUTY_2(PWM41, duty);
    SET_PWM_DUTY_2(PWM42, duty);
}

static void enable_row(uint8_t row)
{
    switch (row) {
        case 0:
            P6_0 = 0;
            break;
        case 1:
            LED_R0 = 0;
            break;
        case 2:
            LED_R1 = 0;
            break;
        case 3:
            LED_R2 = 0;
            break;
        case 4:
            LED_R3 = 0;
            break;
        case 5:
            LED_R4 = 0;
            break;
    }
}

// One LED row per subframe (the tick interleaves these with the matrix scans).
bool indicators_update_step(keyboard_state_t *keyboard, uint8_t current_step)
{
    current_step;

    const bool    awake = !usb_suspended;
    const bool    on    = k630_backlight_on && awake;
    const bool    caps  = (keyboard->led_state & (1 << 1)) && awake;
    const uint8_t  idx  = (uint8_t)(k630_backlight_level - 1u); // unsigned: no signed math
    const uint16_t lit  = led_duty[idx];

    if (on || caps) {
        // (values computed first: smk's SET_PWM_DUTY_2 does not parenthesise its argument)
        const uint16_t all_duty  = on ? lit : 0;
        const uint16_t caps_duty = (on != caps) ? lit : 0;
        set_all_columns(all_duty);
        if (led_row == CAPS_ROW) {
            SET_PWM_DUTY_2(LED_PWM_C0, caps_duty);
        }
        enable_row(led_row);
    }

    if (++led_row >= LED_ROWS) {
        led_row = 0;
    }
    return false;
}

void indicators_post_update()
{
    indicators_pwm_enable();
}

void indicators_pwm_enable()
{
    PWM00CON = PWM_CON_COL; // (stock 0xCA also enables its PWM0 interrupt: not used here)
    PWM01CON = PWM_CON_COL;
    PWM02CON = PWM_CON_COL;
    PWM03CON = PWM_CON_COL;
    PWM04CON = PWM_CON_COL;
    PWM05CON = PWM_CON_COL;

    PWM10CON = PWM_CON_COL;
    PWM11CON = PWM_CON_COL;
    PWM12CON = PWM_CON_COL;
    PWM13CON = PWM_CON_COL;
    PWM14CON = PWM_CON_COL;
    PWM15CON = PWM_CON_COL;

    PWM20CON = PWM_CON_COL;
    PWM21CON = PWM_CON_COL;
    PWM22CON = PWM_CON_COL;
    PWM23CON = PWM_CON_COL;
    PWM24CON = PWM_CON_COL;
    PWM25CON = PWM_CON_COL;

    PWM40CON = PWM_CON_COL;
    PWM41CON = PWM_CON_COL;
    PWM42CON = PWM_CON_COL;
}

void indicators_pwm_disable() // pins released, counters keep running (stock phase 0)
{
    PWM00CON = PWM_CON_IDLE;
    PWM01CON = PWM_CON_IDLE;
    PWM02CON = PWM_CON_IDLE;
    PWM03CON = PWM_CON_IDLE;
    PWM04CON = PWM_CON_IDLE;
    PWM05CON = PWM_CON_IDLE;

    PWM10CON = PWM_CON_IDLE;
    PWM11CON = PWM_CON_IDLE;
    PWM12CON = PWM_CON_IDLE;
    PWM13CON = PWM_CON_IDLE;
    PWM14CON = PWM_CON_IDLE;
    PWM15CON = PWM_CON_IDLE;

    PWM20CON = PWM_CON_IDLE;
    PWM21CON = PWM_CON_IDLE;
    PWM22CON = PWM_CON_IDLE;
    PWM23CON = PWM_CON_IDLE;
    PWM24CON = PWM_CON_IDLE;
    PWM25CON = PWM_CON_IDLE;

    PWM40CON = PWM_CON_IDLE;
    PWM41CON = PWM_CON_IDLE;
    PWM42CON = PWM_CON_IDLE;
}
