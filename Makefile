# Host-side build: keyd oracle tools, config export, the firmware engine on the host, and the
# differential tests. Firmware images are built with meson in third_party/smk (see docs/DESIGN.md).
#
#   make test                       difftest keymap/rynsf.conf and tests/configs/coverage.conf
#   make test-config CONFIG=x.conf  difftest one config

KEYD    := third_party/keyd/src
KEYD_C  := $(KEYD)/keyboard.c $(KEYD)/string.c $(KEYD)/macro.c $(KEYD)/config.c \
           $(KEYD)/log.c $(KEYD)/ini.c $(KEYD)/keys.c $(KEYD)/unicode.c
KEYD_CFLAGS := -std=c11 -D_DEFAULT_SOURCE -O1 -Wno-unused -DVERSION='"v2.6.0"' \
           -DDATA_DIR='"/usr/share/keyd"' -DCONFIG_DIR='"/etc/keyd"' -iquote $(KEYD) \
           -iquote tools/keyd-oracle
TOOLS   := tools/bin/keyd-oracle tools/bin/keyd-inspect tools/bin/keyd-export
ENGINE  := engine/kd.c engine/kd.h engine/kd_config.h

CONFIG  ?= keymap/rynsf.conf
NAME    := $(basename $(notdir $(CONFIG)))
OUT     := build/$(NAME)
RANDOM  ?= 5000
SEED    ?= 1

.PHONY: all tools test test-config clean
all: tools $(OUT)/kd-host

tools: $(TOOLS)

tools/bin/keyd-%: tools/keyd-oracle/%.c tools/keyd-oracle/quiet_parse.h $(KEYD_C)
	@mkdir -p tools/bin
	$(CC) $(KEYD_CFLAGS) $< $(KEYD_C) -o $@

$(OUT)/kd_config_gen.c: tools/bin/keyd-export $(CONFIG)
	@mkdir -p $(OUT)
	tools/bin/keyd-export $(CONFIG) > $@ 2>$(OUT)/export.log || (cat $(OUT)/export.log; rm -f $@; false)

$(OUT)/kd-host: tests/kd_host.c $(ENGINE) $(OUT)/kd_config_gen.c
	$(CC) -std=c11 -O1 -g -Wall -Wextra -Wno-unused-parameter -fsanitize=address,undefined \
		-Iengine -iquote $(KEYD) tests/kd_host.c engine/kd.c $(OUT)/kd_config_gen.c \
		$(KEYD)/keys.c -o $@

test-config: tools $(OUT)/kd-host
	KD_HOST=$(OUT)/kd-host python3 -I tests/difftest.py --config $(CONFIG) --random $(RANDOM) --seed $(SEED)

test:
	$(MAKE) --no-print-directory test-config CONFIG=keymap/rynsf.conf
	$(MAKE) --no-print-directory test-config CONFIG=tests/configs/coverage.conf

clean:
	rm -rf build $(TOOLS)
