/*
 * kd-host: the firmware engine (engine/kd.c + generated tables) on the host, with the same
 * script/output format as tools/keyd-oracle/oracle.c, so the two can be diffed.
 *
 * usage: kd-host <script>
 * Key names come from keyd's keys.c (linked in), so output text is identical to the oracle's.
 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "kd.h"
#include "keys.h"

static long now;

void kd_output(uint8_t code, uint8_t pressed)
{
	const char *name = keycode_table[code].name;
	if (name)
		printf("%ld %s %s\n", now, name, pressed ? "down" : "up");
	else
		printf("%ld code%u %s\n", now, code, pressed ? "down" : "up");
}

static uint8_t lookup_code(const char *name)
{
	for (size_t i = 0; i < 256; i++)
		if (keycode_table[i].name && !strcmp(keycode_table[i].name, name))
			return i;
	for (size_t i = 0; i < 256; i++)
		if (keycode_table[i].alt_name && !strcmp(keycode_table[i].alt_name, name))
			return i;
	return 0;
}

static long deadline;

static void feed(uint8_t code, uint8_t pressed, long t)
{
	now = t;
	long timeout = kd_event(code, pressed, t);
	deadline = timeout > 0 ? t + timeout : 0;
}

static void run_timeouts_until(long t)
{
	while (deadline && deadline <= t)
		feed(0, 0, deadline);
}

int main(int argc, char *argv[])
{
	char line[256];
	long t = 0;

	if (argc != 2) {
		fprintf(stderr, "usage: %s <script>\n", argv[0]);
		return 2;
	}
	FILE *f = fopen(argv[1], "r");
	if (!f) {
		perror(argv[1]);
		return 2;
	}
	kd_init();

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
			fprintf(stderr, "%s:%d: bad line\n", argv[1], ln);
			return 2;
		}
		uint8_t code = lookup_code(key);
		if (!code) {
			fprintf(stderr, "%s:%d: unknown key '%s'\n", argv[1], ln, key);
			return 2;
		}
		run_timeouts_until(t);
		feed(code, !strcmp(state, "down"), t);
	}
	run_timeouts_until(t + 100000);
	if (getenv("KD_STATS"))
		fprintf(stderr, "peak_frames=%u\n", kd_peak_frames);
	if (kd_overflow)
		fprintf(stderr, "kd_overflow=%u\n", kd_overflow);
	return 0;
}
