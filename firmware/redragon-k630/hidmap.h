#pragma once

#include <stdint.h>

#ifndef __SDCC
#    define __code
#endif

#define HIDMAP_KEYS     0x74
#define HIDMAP_CONSUMER 9

struct hidmap_consumer {
    uint8_t  code;
    uint16_t usage;
};

extern const __code uint8_t                hid_to_keyd[HIDMAP_KEYS];
extern const __code uint8_t                hidmod_to_keyd[8];
extern const __code uint8_t                keyd_to_hid[256];
extern const __code struct hidmap_consumer hidmap_consumer[HIDMAP_CONSUMER];
