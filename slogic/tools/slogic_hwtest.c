/*
 * slogic_hwtest — drive the libslogic capture engine directly on hardware.
 * Not vendored into the front ends; for bring-up and regression only.
 *
 * Copyright (C) 2023-2025 Shenzhen Sipeed Technology Co., Ltd.
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * cc -std=gnu11 -O2 -Islogic slogic/slogic.c slogic/slogic8u2.c \
 *    slogic/slogic16u3.c slogic/slogic32u3.c slogic/slogic_data.c \
 *    slogic/slogic_usb.c slogic/tools/slogic_hwtest.c \
 *    $(pkg-config --cflags --libs libusb-1.0) -lpthread -o slogic_hwtest
 *
 * slogic_hwtest [-c CH] [-r MHZ] [-n SAMPLES|0] [-t D<i>=r|f|e|0|1] [-p PRE]
 *               [-P normal|usb|emu] [-s STOP_AFTER_MS] [-l LOOPS] [-o FILE] [-v]
 */

#include <libusb.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#include "slogic.h"

static int verbose;
static FILE *out;
static unsigned long long got;
static long long trig_at = -1;

static void logfn(void *u, int level, const char *msg)
{
	(void)u;
	if (level <= SLOGIC_LOG_INFO || (verbose && level <= SLOGIC_LOG_DBG) ||
	    verbose > 1)
		fprintf(stderr, "slogic[%d]: %s\n", level, msg);
}

static int on_data(void *u, const uint8_t *s, size_t n, unsigned unit)
{
	(void)u;
	if (out)
		fwrite(s, unit, n, out);
	got += n;
	return 0;
}

static void on_trig(void *u, uint64_t idx)
{
	(void)u;
	trig_at = (long long)idx;
}

static long long ms_now(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

int main(int argc, char **argv)
{
	int ch = 32, opt, loops = 1, i, rc = 0;
	double mhz = 200;
	unsigned long long n = 1000000, pre = 0;
	long long stop_after = -1;
	const char *trig = NULL, *file = NULL;
	int pattern = SLOGIC_PATTERN_EMULATION;
	libusb_context *ctx;
	libusb_device *dev;
	slogic_dev *d;

	while ((opt = getopt(argc, argv, "c:r:n:t:p:P:s:l:o:v")) != -1) {
		switch (opt) {
		case 'c': ch = atoi(optarg); break;
		case 'r': mhz = atof(optarg); break;
		case 'n': n = strtoull(optarg, NULL, 0); break;
		case 't': trig = optarg; break;
		case 'p': pre = strtoull(optarg, NULL, 0); break;
		case 'P': pattern = !strcmp(optarg, "normal") ? SLOGIC_PATTERN_NORMAL :
				    !strcmp(optarg, "usb") ? SLOGIC_PATTERN_USB_TEST :
				    SLOGIC_PATTERN_EMULATION; break;
		case 's': stop_after = atoll(optarg); break;
		case 'l': loops = atoi(optarg); break;
		case 'o': file = optarg; break;
		case 'v': verbose++; break;
		default: fprintf(stderr, "bad option\n"); return 2;
		}
	}
	if (libusb_init(&ctx) || slogic_find(ctx, 0, NULL, NULL, &dev) != SLOGIC_OK) {
		fprintf(stderr, "no SLogic found\n");
		return 1;
	}
	if ((rc = slogic_dev_open(ctx, dev, logfn, NULL, &d)) != SLOGIC_OK) {
		fprintf(stderr, "open failed %d\n", rc);
		return 1;
	}
	libusb_unref_device(dev);

	for (i = 0; i < loops; i++) {
		slogic_capture_config cfg;
		slogic_capture *c;
		slogic_report rep;
		long long t0;

		memset(&cfg, 0, sizeof(cfg));
		cfg.dev.channel_count = ch;
		cfg.dev.samplerate_hz = (uint64_t)(mhz * 1e6);
		cfg.dev.threshold_v = 1.7;
		cfg.dev.pattern_mode = pattern;
		cfg.limit_samples = n;
		cfg.pretrigger_samples = pre;
		cfg.sink.data = on_data;
		cfg.sink.trigger = on_trig;
		if (trig && trig[0] == 'D') {
			int idx = atoi(trig + 1);
			const char *eq = strchr(trig, '=');
			char k = eq ? eq[1] : 'r';
			cfg.trigger.match[idx] = k == 'r' ? SLOGIC_TRIG_RISING :
				k == 'f' ? SLOGIC_TRIG_FALLING : k == 'e' ? SLOGIC_TRIG_EDGE :
				k == '0' ? SLOGIC_TRIG_ZERO : SLOGIC_TRIG_ONE;
		}
		out = file ? fopen(file, "wb") : NULL;
		got = 0;
		trig_at = -1;
		t0 = ms_now();
		if ((rc = slogic_capture_start(d, &cfg, &c)) != SLOGIC_OK) {
			fprintf(stderr, "start failed %d\n", rc);
			break;
		}
		while (slogic_capture_poll(c, 8, 10) == SLOGIC_CAP_RUNNING)
			if (stop_after >= 0 && ms_now() - t0 > stop_after)
				slogic_capture_stop(c);
		slogic_capture_report(c, &rep);
		printf("loop %d: delivered=%llu trig=%lld wall_ms=%lld end=%d\n", i, got,
		       trig_at, ms_now() - t0, (int)rep.end);
		slogic_capture_destroy(c);
		if (out)
			fclose(out);
		if (rep.end == SLOGIC_END_ERROR)
			rc = 3;
	}
	slogic_dev_close(d);
	libusb_exit(ctx);
	return rc;
}
