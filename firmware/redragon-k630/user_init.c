#include "kbdef.h"
#include "user_init.h"
#include "gpio.h"

// Pin setup. Matrix pins as on the Z11 (same reference design). The other outputs the
// stock firmware drives at init (0x57F0) are set to the same levels here, since their
// purpose is unknown (P0.2/P0.4 high, P4.4 low, P5.5/P5.6 low, P7.5 high). The
// backlight is left unpowered: no PWM is started (Phase 4).
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
    GPIO_DIR_WRITE(6, (uint8_t)(LED_R0_P6_1 | LED_R1_P6_2 | LED_R2_P6_3 | LED_R3_P6_4 | LED_R4_P6_5));
    GPIO_DIR_WRITE(7, (uint8_t)(_P7_5));

    // row inputs pulled up
    GPIO_PULLUP_WRITE(5, (uint8_t)(KB_R3_P5_3 | KB_R4_P5_4));
    GPIO_PULLUP_WRITE(7, (uint8_t)(KB_R0_P7_1 | KB_R1_P7_2 | KB_R2_P7_3));

    // levels: Caps LED off, LED rows idle, columns deselected (high)
    GPIO_WRITE(0, (uint8_t)(_P0_2 | LED_CAPS_P0_3 | _P0_4));
    GPIO_WRITE(4, 0);
    GPIO_LOW(5, (uint8_t)(_P5_5 | _P5_6));
    GPIO_WRITE(6, LED_R0_P6_1 | LED_R1_P6_2 | LED_R2_P6_3 | LED_R3_P6_4 | LED_R4_P6_5);
    GPIO_HIGH(7, (uint8_t)(_P7_5));
}

void user_init()
{
    user_gpio_init();
}
