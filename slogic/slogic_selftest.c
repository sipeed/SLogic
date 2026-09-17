/*
 * libslogic self-test — model registry, ceilings, transfer planning, first
 * drop, and the stall watchdog. Pure logic, no hardware, no transport.
 *
 * Copyright (C) 2023-2025 Shenzhen Sipeed Technology Co., Ltd.
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Build the slogic/ sources with: cc -Wall -Wextra -std=c11 ... -o selftest
 */

#include "slogic.h"

#include <stdio.h>
#include <string.h>

static int fails;

#define CHECK(cond) do { \
	if (!(cond)) { printf("FAIL %s:%d  %s\n", __FILE__, __LINE__, #cond); \
		       fails++; } \
} while (0)

static void test_models(void)
{
	const slogic_model *c8 = slogic_model_for_pid(SLOGIC_PID_COMBO8);
	const slogic_model *m16 = slogic_model_for_pid(SLOGIC_PID_16U3);
	const slogic_model *m32 = slogic_model_for_pid(SLOGIC_PID_32U3);
	size_t n = 0;

	CHECK(c8 && strcmp(c8->name, "SLogic Combo 8") == 0);
	CHECK(m16 && m16->pid == 0x3031 && m16->ep_in == 0x82);
	CHECK(m32 && m32->pid == 0x3032 && m32->physical_channels == 32);
	CHECK(slogic_model_for_pid(0x30f1) == NULL); /* DFU is not a runtime model */
	CHECK(slogic_models(&n) != NULL && n == 3);

	/* Ceilings: same physical mapping the two drivers agree on. */
	CHECK(slogic_max_rate(m16, 4, 0) == SLOGIC_MHZ(800));
	CHECK(slogic_max_rate(m16, 8, 0) == SLOGIC_MHZ(400));
	CHECK(slogic_max_rate(m16, 16, 0) == SLOGIC_MHZ(200));
	CHECK(slogic_max_rate(m16, 16, 1) == SLOGIC_MHZ(100)); /* Windows cap */
	CHECK(slogic_max_rate(m32, 4, 0) == SLOGIC_MHZ(1600));
	CHECK(slogic_max_rate(m32, 32, 0) == SLOGIC_MHZ(200));
	CHECK(slogic_max_rate(m32, 32, 1) == SLOGIC_MHZ(200)); /* no Windows table */
	CHECK(slogic_max_rate(c8, 8, 0) == SLOGIC_MHZ(40));
	CHECK(slogic_max_rate(m16, 5, 0) == 0);  /* not a mode */
}

static void test_plan(void)
{
	slogic_config c = { .channel_count = 32, .samplerate_hz = SLOGIC_MHZ(200) };
	slogic_transfer_plan p;

	/* 32ch @ 200 MHz -> 800 MB/s. */
	CHECK(slogic_plan_transfers(&c, SLOGIC_SIZING_ALLLOGIC, &p) == SLOGIC_OK);
	CHECK(p.expected_rate_bytes == 800000000u);
	CHECK(p.ring_count == 16);
	CHECK(p.size_bytes >= 32u * 1024u && p.size_bytes <= 3u * 1024u * 1024u);
	CHECK(p.size_bytes % (32u * 1024u) == 0);
	CHECK(p.timeout_ms >= 10);

	CHECK(slogic_plan_transfers(&c, SLOGIC_SIZING_LIBSIGROK, &p) == SLOGIC_OK);
	CHECK(p.expected_rate_bytes == 800000000u);
	CHECK(p.size_bytes >= 32u * 1024u);       /* no upper cap for libsigrok */
	CHECK(p.size_bytes % (32u * 1024u) == 0);

	CHECK(slogic_plan_transfers(NULL, SLOGIC_SIZING_ALLLOGIC, &p) == SLOGIC_ERR_ARG);
}

static void test_first_drop(void)
{
	slogic_stream s;
	uint8_t buf[16];
	size_t kept;

	slogic_stream_init(&s, NULL, 0);
	CHECK(s.drop_left == 4);

	/* A short first transfer consumes only part of the 4-byte drop. */
	memset(buf, 0xAA, sizeof(buf));
	kept = slogic_apply_first_drop(&s, buf, 2);
	CHECK(kept == 0 && s.drop_left == 2);
	/* The rest of the drop is taken from the next transfer. */
	kept = slogic_apply_first_drop(&s, buf, 8);
	CHECK(kept == 6 && s.drop_left == 0);
	/* Once satisfied, later transfers pass through untouched. */
	kept = slogic_apply_first_drop(&s, buf, 8);
	CHECK(kept == 8 && s.drop_left == 0);
}

static void test_watch_done(void)
{
	slogic_transfer_plan p = { .size_bytes = 3145728, .ring_count = 16,
				   .expected_rate_bytes = 800000000u };
	slogic_stream s;

	slogic_stream_init(&s, &p, 5000000);
	/* A full, on-time transfer keeps the capture going... */
	CHECK(slogic_stream_watch(&s, 3145728, 4000, 4000) == SLOGIC_STREAM_OK);
	/* ...until the requested byte count is reached. */
	CHECK(slogic_stream_watch(&s, 3145728, 8000, 4000) == SLOGIC_STREAM_DONE);
}

static void test_watch_never_started(void)
{
	slogic_transfer_plan p = { .size_bytes = 3145728, .ring_count = 4,
				   .expected_rate_bytes = 800000000u };
	slogic_stream s;
	slogic_verdict v = SLOGIC_STREAM_OK;
	int i;
	int64_t now = 0;

	slogic_stream_init(&s, &p, 0);
	/* 4 slow, zero-byte transfers -> RETRY_RUN once. */
	for (i = 0; i < 4; i++) {
		now += 100000; /* 100 ms >> expected ~3.9 ms */
		v = slogic_stream_watch(&s, 0, now, 100000);
	}
	CHECK(v == SLOGIC_STREAM_RETRY_RUN);
	CHECK(s.run_retried == 1);
	/* Still nothing after the re-arm -> ABORT. */
	for (i = 0; i < 4; i++) {
		now += 100000;
		v = slogic_stream_watch(&s, 0, now, 100000);
	}
	CHECK(v == SLOGIC_STREAM_ABORT);
}

static void test_watch_backpressure(void)
{
	slogic_transfer_plan p = { .size_bytes = 3145728, .ring_count = 16,
				   .expected_rate_bytes = 800000000u };
	slogic_stream s;
	slogic_verdict v;

	slogic_stream_init(&s, &p, 0);
	/* First a healthy transfer so data is flowing. */
	v = slogic_stream_watch(&s, 3145728, 4000, 4000);
	CHECK(v == SLOGIC_STREAM_OK);
	/* A full transfer that arrives late (host backpressure) warns exactly
	 * once and never aborts. */
	v = slogic_stream_watch(&s, 3145728, 100000, 96000);
	CHECK(v == SLOGIC_STREAM_WARN_SLOW);
	v = slogic_stream_watch(&s, 3145728, 200000, 100000);
	CHECK(v == SLOGIC_STREAM_OK); /* warning is one-shot */
}

static void test_watch_idle_abort(void)
{
	slogic_transfer_plan p = { .size_bytes = 3145728, .ring_count = 16,
				   .expected_rate_bytes = 800000000u };
	slogic_stream s;
	slogic_verdict v;

	slogic_stream_init(&s, &p, 0);
	CHECK(slogic_stream_watch(&s, 3145728, 4000, 4000) == SLOGIC_STREAM_OK);
	/* No data for > 1 s after the last bytes -> fatal. */
	v = slogic_stream_watch(&s, 0, 4000 + 1100000, 1100000);
	CHECK(v == SLOGIC_STREAM_ABORT);
}

int main(void)
{
	test_models();
	test_plan();
	test_first_drop();
	test_watch_done();
	test_watch_never_started();
	test_watch_backpressure();
	test_watch_idle_abort();

	if (fails) {
		printf("%d check(s) FAILED\n", fails);
		return 1;
	}
	printf("all libslogic self-tests pass\n");
	return 0;
}
