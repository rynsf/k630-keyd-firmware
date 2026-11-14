// K630 backlight: one mode, every key at one brightness, on or off.
//
// The LED circuit is the same as the E-YOOSO Z11's (checked against the stock firmware's
// LED driver: rows P6.1-P6.5 active low, one PWM channel per key column, the same 14
// channels; see re/K630-HARDWARE.md). This is smk's Z11 driver without the effects.
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
#define LED_DUTY(v) (uint16_t)(0x0400u - ((uint16_t)(v) << 2)) // 0 = dark, 255 = full

#define LED_ALL_ROWS (uint8_t)(LED_R0_P6_1 | LED_R1_P6_2 | LED_R2_P6_3 | LED_R3_P6_4 | LED_R4_P6_5)

#define CAPS_ROW 2
#define CAPS_COL 0

static const __code uint8_t LEVEL[BACKLIGHT_LEVELS] = {16, 48, 96, 160, 255};

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
    const uint8_t v     = LEVEL[k630_backlight_level - 1];

    if (on || caps) {
        set_all_columns(LED_DUTY(on ? v : 0));
        if (led_row == CAPS_ROW) {
            SET_PWM_DUTY_2(LED_PWM_C0, LED_DUTY((on != caps) ? v : 0));
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
    PWM00CON = (uint8_t)(PWM_MODE_ENABLE | PWM_INT_ENABLE | PWM_SS | PWM_CLK_DIV_4);
    PWM01CON = PWM_SS;
    PWM02CON = PWM_SS;
    PWM03CON = PWM_SS;
    PWM04CON = PWM_SS;
    PWM05CON = PWM_SS;

    PWM10CON = (uint8_t)(PWM_MODE_ENABLE | PWM_SS | PWM_CLK_DIV_4);
    PWM11CON = PWM_SS;
    PWM12CON = PWM_SS;
    PWM13CON = PWM_SS;
    PWM14CON = PWM_SS;
    PWM15CON = PWM_SS;

    PWM20CON = (uint8_t)(PWM_MODE_ENABLE | PWM_SS | PWM_CLK_DIV_4);
    PWM24CON = PWM_SS;
    PWM25CON = PWM_SS;
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
