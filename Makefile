# Host-side build: keyd oracle tools, config export, the firmware engine on the host, and the
# differential tests. Firmware images are built with meson in third_party/smk (see docs/DESIGN.md).
#
#   make test                       difftest keymap/rynsf.conf and tests/configs/coverage.conf
#   make test-config CONFIG=x.conf  difftest one config
#   make firmware                   build the K630 image (build/smk/), flashes nothing
#   make test-firmware              simulator tests of that image + image vs keyd

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

SMK      := third_party/smk
FW_BUILD := build/smk
FW_NAME  := redragon-k630_default_smk.hex
FW_GEN   := firmware/redragon-k630/kd_config_gen.c
TOOLPATH := PATH=$(CURDIR)/tools/bin:$$PATH

.PHONY: all tools test test-config firmware test-firmware canary clean FORCE
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

# Firmware image (never flashes anything). The board dir is linked into smk's tree and
# smk's core changes come from firmware/smk.patch (see tools/setup.sh).
# regenerated on every build (CONFIG may differ from last time); replaced only on change
$(FW_GEN): tools/bin/keyd-export FORCE
	tools/bin/keyd-export $(CONFIG) > $@.tmp 2>$(FW_GEN).log || (cat $(FW_GEN).log; rm -f $@.tmp; false)
	if cmp -s $@.tmp $@; then rm $@.tmp; else mv $@.tmp $@; fi

FORCE:

firmware: $(FW_GEN)
	@[ -d $(FW_BUILD) ] || $(TOOLPATH) meson setup $(FW_BUILD) $(SMK) --buildtype=release -Dboot=disabled
	$(TOOLPATH) meson compile -C $(FW_BUILD) $(FW_NAME)
	@echo "image: $(FW_BUILD)/$(FW_NAME)"

# Simulator tests of the image above, then the image vs keyd itself (SIM_RANDOM scripts).
SIM_RANDOM ?= 1000
test-firmware: firmware
	cd tests/firmware && $(TOOLPATH) python3 -m unittest -v test_k630
	$(TOOLPATH) python3 tests/firmware/sim_difftest.py --config $(CONFIG) --random $(SIM_RANDOM) --seed $(SEED) --pins 0 --jobs 12

# The canary for the first flash: the same image with the pass-through config, kept as its
# own file (build/canary/). Tests run against it, then the normal image is rebuilt.
canary:
	$(MAKE) --no-print-directory firmware CONFIG=tests/configs/passthrough.conf
	mkdir -p build/canary
	rm -rf build/canary/* && cp -r $(FW_BUILD)/redragon-k630_default_smk.* $(FW_BUILD)/user.lib.p build/canary/
	cd tests/firmware && K630_FIRMWARE=$(CURDIR)/build/canary/$(FW_NAME) K630_CONFIG=tests/configs/passthrough.conf $(TOOLPATH) python3 -m unittest test_k630
	K630_FIRMWARE=$(CURDIR)/build/canary/$(FW_NAME) $(TOOLPATH) python3 tests/firmware/sim_difftest.py --config tests/configs/passthrough.conf --random 300 --seed 4 --pins 0 --jobs 12
	$(MAKE) --no-print-directory firmware
	@sha256sum build/canary/$(FW_NAME)

clean:
	rm -rf build $(TOOLS)
