# Build tx_ddr on the Raspberry Pi 5 (native, aarch64, libgpiod v2).
#
# Requires: sudo apt install build-essential libgpiod-dev
#   Pi OS Bookworm ships libgpiod v2 (headers: gpiod.h v2 API). If `make` errors
#   with "unknown type name 'gpiod_line_settings'", you have v1 -- see README.
#
# Targets:
#   make            -> ./tx_ddr
#   make run-carrier-> continuous carrier (tune the analyzer), Ctrl-C to stop
#   make clean

CC      ?= cc
CFLAGS  ?= -O2 -std=gnu11 -Wall -Wextra
LDLIBS  := $(shell pkg-config --libs libgpiod 2>/dev/null || echo -lgpiod)
CFLAGS  += $(shell pkg-config --cflags libgpiod 2>/dev/null)

tx_ddr: tx_ddr.c
	$(CC) $(CFLAGS) $< -o $@ $(LDLIBS)

.PHONY: run-carrier clean
run-carrier: tx_ddr
	rm -f /tmp/tx_stop
	sudo ./tx_ddr --carrier

clean:
	rm -f tx_ddr
