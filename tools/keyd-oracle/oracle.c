/*
 * keyd-oracle: replay a timed key script through keyd's own processing core (v2.6.0) and print
 * the output, exactly as the keyd daemon would see it. This is the reference the firmware
 * engine is diffed against.
 *
 * usage: oracle <config> <script>
 *
 * Script lines (blank lines and '#' comments are ignored):
 *   <key> down|up      a key event at the current time
 *   <N>ms              advance the current time by N ms
 * Key names are keyd's (a, leftshift, capslock, ...).
 *
 * Output: one line per emitted key event, "<ms> <key> down|up".
 *
 * Timing follows the daemon (src/daemon.c event_handler): each input is fed alone, and when
 * kbd_process_events() returns a timeout, a code-0 event is delivered at that deadline if no
 * input arrives first. After the script, pending timeouts are run to completion.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "keyd.h"
#include "quiet_parse.h"

static long now;

static void send_key(uint8_t code, uint8_t pressed)
{
	const char *name = keycode_table[code].name;
	if (name)
		printf("%ld %s %s\n", now, name, pressed ? "down" : "up");
	else
		printf("%ld code%u %s\n", now, code, pressed ? "down" : "up");
}

static void on_layer_change(const struct keyboard *kbd, const struct layer *layer, uint8_t active)
{
}

static uint8_t lookup_code(const char *name)
{
	for (size_t i = 0; i < ARRAY_SIZE(keycode_table); i++)
		if (keycode_table[i].name && !strcmp(keycode_table[i].name, name))
			return i;
	for (size_t i = 0; i < ARRAY_SIZE(keycode_table); i++)
		if (keycode_table[i].alt_name && !strcmp(keycode_table[i].alt_name, name))
			return i;
	return 0;
}

static long deadline; /* absolute ms, 0 = none */

static void feed(struct keyboard *kbd, uint8_t code, uint8_t pressed, long t)
{
	struct key_event ev = { .code = code, .pressed = pressed, .timestamp = t };
	now = t;
	long timeout = kbd_process_events(kbd, &ev, 1);
	deadline = timeout > 0 ? t + timeout : 0;
}

static void run_timeouts_until(struct keyboard *kbd, long t)
{
	while (deadline && deadline <= t)
		feed(kbd, 0, 0, deadline);
}

int main(int argc, char *argv[])
{
	static struct config config;
	struct output output = { .send_key = send_key, .on_layer_change = on_layer_change };
	char line[256];
	long t = 0;

	if (argc != 3) {
		fprintf(stderr, "usage: %s <config> <script>\n", argv[0]);
		return 2;
	}
	if (config_parse_quiet(&config, argv[1]) < 0) { /* >0 = warnings only, as the daemon accepts */
		fprintf(stderr, "failed to parse config %s\n", argv[1]);
		return 2;
	}
	FILE *f = fopen(argv[2], "r");
	if (!f) {
		perror(argv[2]);
		return 2;
	}

	struct keyboard *kbd = new_keyboard(&config, &output);

	int ln = 0;
	while (fgets(line, sizeof line, f)) {
		char key[64], state[16];
		long ms;
		ln++;
		char *p = line;
		while (*p == ' ' || *p == '\t')
			p++;
		if (*p == '\n' || *p == '#' || *p == 0)
			continue;
		if (sscanf(p, "%ldms", &ms) == 1 && strstr(p, "ms")) {
			t += ms;
			continue;
		}
		if (sscanf(p, "%63s %15s", key, state) != 2) {
			fprintf(stderr, "%s:%d: bad line\n", argv[2], ln);
			return 2;
		}
		uint8_t code = lookup_code(key);
		if (!code) {
			fprintf(stderr, "%s:%d: unknown key '%s'\n", argv[2], ln, key);
			return 2;
		}
		run_timeouts_until(kbd, t);
		feed(kbd, code, !strcmp(state, "down"), t);
	}
	/* let anything still pending (oneshot timeout, overload timeout) resolve */
	run_timeouts_until(kbd, t + 100000);
	return 0;
}
