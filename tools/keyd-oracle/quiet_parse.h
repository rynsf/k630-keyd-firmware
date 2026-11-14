/* keyd's logger prints config warnings to stdout; run the parser with stdout sent to stderr so
 * tool output (generated C, event traces) stays clean. */
#ifndef QUIET_PARSE_H
#define QUIET_PARSE_H
#include <stdio.h>
#include <unistd.h>
#include "keyd.h"

static int config_parse_quiet(struct config *c, const char *path)
{
	fflush(stdout);
	int saved = dup(1);
	dup2(2, 1);
	int ret = config_parse(c, path);
	fflush(stdout);
	dup2(saved, 1);
	close(saved);
	return ret;
}
#endif
