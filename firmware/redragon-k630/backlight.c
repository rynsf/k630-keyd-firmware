// K630 backlight: one mode, every key at one brightness, on or off.
//
// LED circuit (from the stock firmware's driver, re/K630-HARDWARE.md): rows P6.1-P6.5
// active low, one PWM channel per key column (the same 14 channels as the Z11). The PWM
// setup copies the stock firmware exactly, not smk's Z11 driver: every column channel is
// enabled (0x8A), the column pins are inputs without pull-up during the LED phase so the
// PWM drives them, period 0x0DFC, duty1 0, duty2 = brightness (higher = brighter). With
// the Z11 setup most columns were never under PWM: brightness barely changed on the K630.
//
// Caps Lock is shown on the Caps Lock key itself, as the inverse of the backlight: with
// the backlight off it is the only lit key, with the backlight on it is the only dark one.
// The separate Caps LED (P0.3) is never driven.
//
// Nothing is saved (no flash writes): every power-up starts on, at full brightness. While
// the host has the USB bus suspended, everything is dark.
#include "indicators.h"
#include "sh68f90.h"
#include "kbdef.h"
#include "gpio.h"
#include "pwm.h"
#include "usb.h"
#include "backlight.h"

#define LED_ROWS 5
// stock: duty = level * 50 * 14 for levels 1..5, out of the period 0x0DFC (3580)
#define LED_DUTY_STEP 700u
#define COL_P1        (uint8_t)(KB_C0_P1_4 | KB_C1_P1_5)
#define COL_P2        (uint8_t)(KB_C2_P2_0 | KB_C3_P2_1 | KB_C4_P2_2 | KB_C5_P2_3 | KB_C6_P2_4 | KB_C7_P2_5)
#define COL_P3        (uint8_t)(KB_C8_P3_0 | KB_C9_P3_1 | KB_C10_P3_2 | KB_C11_P3_3 | KB_C12_P3_4 | KB_C13_P3_5)
#define PWM_CON_COL   0x8A // stock: MODE_ENABLE | SS | CLK/4, on every column channel

#define LED_ALL_ROWS (uint8_t)(LED_R0_P6_1 | LED_R1_P6_2 | LED_R2_P6_3 | LED_R3_P6_4 | LED_R4_P6_5)

#define CAPS_ROW 2
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
    k630_backlight_on    = 1;
    k630_backlight_level = BACKLIGHT_LEVELS;
    indicators_pwm_enable();
}

void indicators_pre_update()
{
    GPIO_HIGH(6, LED_ALL_ROWS); // all LED rows off while the columns change
    indicators_pwm_disable();
    // hand the column pins to the PWM block (stock 0x427A); user_matrix_scan_pre() takes
    // them back before every matrix scan
    GPIO_INPUT(1, COL_P1);
    GPIO_PULLUP_OFF(1, COL_P1);
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
}

static void enable_row(uint8_t row)
{
    switch (row) {
        case 0:
            LED_R0 = 0;
            break;
        case 1:
            LED_R1 = 0;
            break;
        case 2:
            LED_R2 = 0;
            break;
        case 3:
            LED_R3 = 0;
            break;
        case 4:
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
    const uint16_t lit  = (uint16_t)k630_backlight_level * LED_DUTY_STEP;

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
    PWM00CON &= ~(1 << 5);
    indicators_pwm_enable();
}

void indicators_pwm_enable()
{
    PWM00CON = (uint8_t)(PWM_CON_COL | PWM_INT_ENABLE); // stock 0xCA: also the PWM0 interrupt
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
    PWM24CON = PWM_CON_COL;
    PWM25CON = PWM_CON_COL;
}

void indicators_pwm_disable()
{
    PWM00CON = PWM_CON_PARKED;
    PWM01CON = PWM_CON_OFF;
    PWM02CON = PWM_CON_OFF;
    PWM03CON = PWM_CON_OFF;
    PWM04CON = PWM_CON_OFF;
    PWM05CON = PWM_CON_OFF;

    PWM10CON = PWM_CON_PARKED;
    PWM11CON = PWM_CON_OFF;
    PWM12CON = PWM_CON_OFF;
    PWM13CON = PWM_CON_OFF;
    PWM14CON = PWM_CON_OFF;
    PWM15CON = PWM_CON_OFF;

    PWM20CON = PWM_CON_PARKED;
    PWM24CON = PWM_CON_OFF;
    PWM25CON = PWM_CON_OFF;
}
