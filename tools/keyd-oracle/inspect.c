/* Print what keyd v2.6.0's own parser makes of a config: layers, types, mods, bindings, ops. */
#include <stdio.h>
#include <string.h>
#include "keyd.h"
#include "quiet_parse.h"

static const char *opname[] = {
	[OP_KEYSEQUENCE] = "keyseq", [OP_ONESHOT] = "oneshot", [OP_ONESHOTM] = "oneshotm",
	[OP_ONESHOTK] = "oneshotk", [OP_LAYERM] = "layerm", [OP_SWAP] = "swap", [OP_SWAPM] = "swapm",
	[OP_LAYER] = "layer", [OP_LAYOUT] = "layout", [OP_CLEAR] = "clear", [OP_CLEARM] = "clearm",
	[OP_OVERLOAD] = "overload", [OP_OVERLOAD_TIMEOUT] = "overloadt",
	[OP_OVERLOAD_TIMEOUT_TAP] = "overloadt2", [OP_OVERLOAD_IDLE_TIMEOUT] = "overloadi",
	[OP_TOGGLE] = "toggle", [OP_TOGGLEM] = "togglem", [OP_REPEAT] = "repeat", [OP_MACRO] = "macro",
	[OP_MACRO2] = "macro2", [OP_COMMAND] = "command", [OP_TIMEOUT] = "timeout",
};

static const char *kname(int c) { return keycode_table[c].name ? keycode_table[c].name : "?"; }

static void pdesc(const struct config *c, const struct descriptor *d)
{
	printf("%s(", d->op < (int)(sizeof opname / sizeof *opname) && opname[d->op] ? opname[d->op] : "?");
	switch (d->op) {
	case OP_KEYSEQUENCE: printf("%s mods=0x%02x", kname(d->args[0].code), d->args[1].mods); break;
	case OP_LAYER: case OP_ONESHOT: case OP_TOGGLE: case OP_LAYOUT:
		printf("%s", c->layers[d->args[0].idx].name); break;
	case OP_OVERLOAD:
		printf("%s, ", c->layers[d->args[0].idx].name); pdesc(c, &c->descriptors[d->args[1].idx]); break;
	case OP_OVERLOAD_TIMEOUT: case OP_OVERLOAD_TIMEOUT_TAP:
		printf("%s, ", c->layers[d->args[0].idx].name); pdesc(c, &c->descriptors[d->args[1].idx]);
		printf(", %u", d->args[2].timeout); break;
	default: printf("args %d %d %d", d->args[0].idx, d->args[1].idx, d->args[2].idx);
	}
	printf(")");
}

int main(int argc, char **argv)
{
	static struct config c;
	if (argc != 2 || config_parse_quiet(&c, argv[1]) < 0) { fprintf(stderr, "usage: inspect <config>\n"); return 2; }
	printf("layers=%zu descriptors=%zu macros=%zu commands=%zu default_layout='%s'\n",
	       c.nr_layers, c.nr_descriptors, c.nr_macros, c.nr_commands, c.default_layout);
	printf("oneshot_timeout=%ld overload_tap_timeout=%ld macro_timeout=%ld chord_interkey=%ld chord_hold=%ld disable_modifier_guard=%d\n",
	       c.oneshot_timeout, c.overload_tap_timeout, c.macro_timeout, c.chord_interkey_timeout,
	       c.chord_hold_timeout, c.disable_modifier_guard);
	for (size_t i = 0; i < c.nr_layers; i++) {
		const struct layer *l = &c.layers[i];
		int n = 0;
		for (int k = 0; k < 256; k++) n += l->keymap[k].op != 0;
		printf("\n[%zu] %-14s type=%s mods=0x%02x bindings=%d chords=%zu\n", i, l->name,
		       l->type == LT_LAYOUT ? "layout" : l->type == LT_COMPOSITE ? "composite" : "normal",
		       l->mods, n, l->nr_chords);
		for (int k = 0; k < 256; k++)
			if (l->keymap[k].op) { printf("    %-12s = ", kname(k)); pdesc(&c, &l->keymap[k]); printf("\n"); }
	}
	return 0;
}
