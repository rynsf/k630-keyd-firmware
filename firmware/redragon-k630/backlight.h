#pragma once

#include <stdint.h>

#define BACKLIGHT_LEVELS 5

extern uint8_t k630_backlight_on;
extern uint8_t k630_backlight_level;

void backlight_toggle(void);   // FN2 + 0
void backlight_brighter(void); // FN2 + =
void backlight_dimmer(void);   // FN2 + -
