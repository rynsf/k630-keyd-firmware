#include "kbdef.h"
#include "user_init.h"
#include "gpio.h"
#include "pwm.h"

#define PWM_PERD        300 // LED PWM period: 8 periods per LED subframe (backlight.c)
#define PWM_PERDH_INIT  ((uint8_t)(PWM_PERD >> 8))
#define PWM_PERDL_INIT  ((uint8_t)(PWM_PERD))

// Pin setup. Matrix pins as on the Z11 (same reference design). The other outputs the
// stock firmware drives at init (0x57F0) are set to the same levels here, since their
// purpose is unknown (P0.2/P0.4 high, P4.4 low, P5.5/P5.6 low, P7.5 high). The
// backlight is driven by backlight.c. The side Caps LED is on P0.3, active low (stock
// 0x55AF: Caps on -> CLR P0.3); it is kept off by driving P0.3 high permanently. (A
// floating P0.3 let it glow.)
void user_gpio_init(void)
{
    DRVCON = DRVCON_UNLOCK_P1;
    P1DRV  = GPIO_DRIVE_25MA;

    DRVCON = DRVCON_UNLOCK_P2;
    P2DRV  = GPIO_DRIVE_25MA;

    DRVCON = DRVCON_UNLOCK_P3;
    P3DRV  = GPIO_DRIVE_25MA;

    DRVCON = DRVCON_LOCK;

    // outputs
    GPIO_DIR_WRITE(0, (uint8_t)(_P0_2 | LED_CAPS_P0_3 | _P0_4));
    GPIO_DIR_WRITE(1, (uint8_t)(KB_C0_P1_4 | KB_C1_P1_5));
    GPIO_DIR_WRITE(2, (uint8_t)(KB_C2_P2_0 | KB_C3_P2_1 | KB_C4_P2_2 | KB_C5_P2_3 | KB_C6_P2_4 | KB_C7_P2_5));
    GPIO_DIR_WRITE(3, (uint8_t)(KB_C8_P3_0 | KB_C9_P3_1 | KB_C10_P3_2 | KB_C11_P3_3 | KB_C12_P3_4 | KB_C13_P3_5));
    GPIO_DIR_WRITE(4, (uint8_t)(_P4_4));
    GPIO_DIR_WRITE(5, (uint8_t)(_P5_5 | _P5_6));
    GPIO_DIR_WRITE(6, (uint8_t)(_P6_0 | LED_R0_P6_1 | LED_R1_P6_2 | LED_R2_P6_3 | LED_R3_P6_4 | LED_R4_P6_5));
    GPIO_DIR_WRITE(7, (uint8_t)(_P7_5));

    // row inputs pulled up
    GPIO_PULLUP_WRITE(5, (uint8_t)(KB_R3_P5_3 | KB_R4_P5_4));
    GPIO_PULLUP_WRITE(7, (uint8_t)(KB_R0_P7_1 | KB_R1_P7_2 | KB_R2_P7_3));

    // levels: side Caps LED off (high), LED rows idle (off), columns deselected (high)
    GPIO_WRITE(0, (uint8_t)(_P0_2 | LED_CAPS_P0_3 | _P0_4));
    GPIO_WRITE(4, 0);
    GPIO_LOW(5, (uint8_t)(_P5_5 | _P5_6));
    GPIO_WRITE(6, _P6_0 | LED_R0_P6_1 | LED_R1_P6_2 | LED_R2_P6_3 | LED_R3_P6_4 | LED_R4_P6_5);
    GPIO_HIGH(7, (uint8_t)(_P7_5));
}

static void user_pwm_init(void) // as the stock firmware (0x1792...): duty1 = duty2 = 0, dark
                                // (stock period 0x0DFC; ours is shorter, see PWM_PERD)
{
    PWM0PERDH = PWM_PERDH_INIT;
    PWM0PERDL = PWM_PERDL_INIT;
    PWM1PERDH = PWM_PERDH_INIT;
    PWM1PERDL = PWM_PERDL_INIT;
    PWM2PERDH = PWM_PERDH_INIT;
    PWM2PERDL = PWM_PERDL_INIT;
    PWM4PERDH = PWM_PERDH_INIT;
    PWM4PERDL = PWM_PERDL_INIT;

    SET_PWM_DUTY(LED_PWM_C0, 0, 0);
    SET_PWM_DUTY(LED_PWM_C1, 0, 0);
    SET_PWM_DUTY(LED_PWM_C2, 0, 0);
    SET_PWM_DUTY(LED_PWM_C3, 0, 0);
    SET_PWM_DUTY(LED_PWM_C4, 0, 0);
    SET_PWM_DUTY(LED_PWM_C5, 0, 0);
    SET_PWM_DUTY(LED_PWM_C6, 0, 0);
    SET_PWM_DUTY(LED_PWM_C7, 0, 0);
    SET_PWM_DUTY(LED_PWM_C8, 0, 0);
    SET_PWM_DUTY(LED_PWM_C9, 0, 0);
    SET_PWM_DUTY(LED_PWM_C10, 0, 0);
    SET_PWM_DUTY(LED_PWM_C11, 0, 0);
    SET_PWM_DUTY(LED_PWM_C12, 0, 0);
    SET_PWM_DUTY(LED_PWM_C13, 0, 0);
    SET_PWM_DUTY(PWM20, 0, 0); // the stock grid's extra LED columns (backlight.c)
    SET_PWM_DUTY(PWM21, 0, 0);
    SET_PWM_DUTY(PWM22, 0, 0);
    SET_PWM_DUTY(PWM23, 0, 0);
    SET_PWM_DUTY(PWM40, 0, 0);
    SET_PWM_DUTY(PWM41, 0, 0);
    SET_PWM_DUTY(PWM42, 0, 0);
}

void user_init()
{
    user_gpio_init();
    user_pwm_init();
    // No PWM interrupt: smk's handler is empty and never clears the flag (PWM00CON bit 5),
    // which with the 50 us period would re-enter it back to back.
}
