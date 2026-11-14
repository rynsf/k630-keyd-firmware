/*
 * Compiled keyd configuration, generated from a keyd config by tools/keyd-oracle/export.c
 * (which uses keyd v2.6.0's own parser). Lives in code memory on the 8051.
 */
#ifndef KD_CONFIG_H
#define KD_CONFIG_H

#include <stdint.h>

#ifdef __SDCC
#define KD_CODE __code
#else
#define KD_CODE
#endif

/* Same numbering as keyd's enum op (config.h) for the subset the engine implements. */
enum kd_op {
	KD_OP_NONE = 0,
	KD_OP_KEYSEQUENCE = 1,
	KD_OP_ONESHOT = 2,
	KD_OP_LAYER = 8,
	KD_OP_LAYOUT = 9,
	KD_OP_CLEAR = 10,
	KD_OP_OVERLOAD = 12,
	KD_OP_OVERLOAD_TIMEOUT = 13,
	KD_OP_OVERLOAD_TIMEOUT_TAP = 14,
	KD_OP_TOGGLE = 16,
};

/*
 * a0/a1/a2 follow keyd's descriptor args:
 *   KEYSEQUENCE         a0 = keycode, a1 = mods
 *   LAYER/ONESHOT/TOGGLE/LAYOUT  a0 = layer index
 *   OVERLOAD            a0 = layer, a1 = index into kd_descs (tap action)
 *   OVERLOAD_TIMEOUT(_TAP)  a0 = layer, a1 = kd_descs index, a2 = timeout ms
 */
struct kd_desc {
	uint8_t op;
	uint8_t a0;
	uint8_t a1;
	uint16_t a2;
};

struct kd_bind {
	uint8_t code;
	struct kd_desc d;
};

enum { KD_LT_NORMAL = 0, KD_LT_LAYOUT = 1 };

struct kd_layer {
	uint8_t type;
	uint8_t mods;
	uint16_t first; /* index into kd_binds */
	uint8_t n;      /* bindings, sorted by code */
};

struct kd_config {
	uint8_t nr_layers;
	uint8_t default_layout; /* layer index, 0 = none */
	uint16_t oneshot_timeout;
	uint16_t overload_tap_timeout;
	uint8_t disable_modifier_guard;
};

extern const KD_CODE struct kd_desc kd_descs[];
extern const KD_CODE struct kd_bind kd_binds[];
extern const KD_CODE struct kd_layer kd_layers[];
extern const KD_CODE struct kd_config kd_cfg;

#endif
