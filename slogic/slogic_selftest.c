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

/* ---- mock transport: records the control sequence, feeds canned reads ---- */
struct ctl_rec {
	int is_read;
	uint8_t req;
	uint16_t wval;
	uint8_t data[4];
};

struct mock_ctx {
	struct ctl_rec rec[256];
	int n;
	uint8_t last_aux_cmd;
};

static void mock_record(struct mock_ctx *m, int is_read, uint8_t req,
			uint16_t wval, const uint8_t *data, uint16_t len)
{
	struct ctl_rec *r;

	if (m->n >= (int)(sizeof(m->rec) / sizeof(m->rec[0])))
		return;
	r = &m->rec[m->n++];
	r->is_read = is_read;
	r->req = req;
	r->wval = wval;
	memset(r->data, 0, 4);
	memcpy(r->data, data, len < 4 ? len : 4);
}

static int mock_cw(void *ctx, uint8_t req, uint16_t wval, uint16_t widx,
		   const uint8_t *data, uint16_t len, unsigned to)
{
	struct mock_ctx *m = ctx;
	(void)widx;
	(void)to;
	mock_record(m, 0, req, wval, data, len);
	if (wval == 0x000c && req == 0x01)
		m->last_aux_cmd = data[0];
	return len;
}

static int mock_cr(void *ctx, uint8_t req, uint16_t wval, uint16_t widx,
		   uint8_t *data, uint16_t len, unsigned to)
{
	struct mock_ctx *m = ctx;
	(void)req;
	(void)widx;
	(void)to;
	memset(data, 0, len);
	if (wval == 0x000c && len >= 4) {
		/* AUX header: ready bit set; payload length by the last command
		 * (samplerate wants 8 bytes, the others 4). */
		uint32_t nbytes = (m->last_aux_cmd == 0x02) ? 8u : 4u;
		uint32_t h = (1u << 16) | ((nbytes << 9) & 0xffffu);
		data[0] = (uint8_t)h;
		data[1] = (uint8_t)(h >> 8);
		data[2] = (uint8_t)(h >> 16);
		data[3] = (uint8_t)(h >> 24);
	} else if (wval == 0x0010 && m->last_aux_cmd == 0x02 && len >= 4) {
		/* rate payload word0: idx=0, base_mhz=200 -> divides 200 MHz. */
		data[2] = 200;
	}
	mock_record(m, 1, req, wval, data, len);
	return len;
}

static int eq4(const uint8_t *d, uint8_t a, uint8_t b, uint8_t c, uint8_t e)
{
	return d[0] == a && d[1] == b && d[2] == c && d[3] == e;
}

/*
 * Drive the canonical configure/run through the mock and assert the emitted
 * control sequence matches build/bench/slogic_control_vectors.py: CTRL=STOP,
 * AUX channel/rate/vref/pattern in order each confirmed, then CTRL=RUN, no RST.
 */
static void test_control_sequence(void)
{
	struct mock_ctx mk;
	slogic_transport t;
	const slogic_model *m32;
	slogic_config c;
	int i, ctrl_writes = 0, first_ctrl = -1, last_ctrl = -1;
	int aux_seq[8], aux_n = 0;
	int have_mask = 0, have_dac = 0, have_mode = 0, have_rst = 0;
	int mode_write_idx = -1, confirm_after_mode = 0;

	memset(&mk, 0, sizeof(mk));
	t.ctx = &mk;
	t.control_write = mock_cw;
	t.control_read = mock_cr;
	m32 = slogic_model_for_pid(SLOGIC_PID_32U3);
	memset(&c, 0, sizeof(c));
	c.channel_count = 16;
	c.samplerate_hz = SLOGIC_MHZ(200);
	c.threshold_v = 1.7;
	c.pattern_mode = SLOGIC_PATTERN_EMULATION;

	CHECK(slogic_configure(m32, &t, &c) == SLOGIC_OK);
	CHECK(slogic_run(m32, &t, &c) == SLOGIC_OK);

	for (i = 0; i < mk.n; i++) {
		struct ctl_rec *r = &mk.rec[i];
		if (r->is_read) {
			if (r->wval == 0x0010 && mode_write_idx >= 0 &&
			    i > mode_write_idx)
				confirm_after_mode = 1;
			continue;
		}
		if (r->wval == 0x0004) { /* R_CTRL */
			ctrl_writes++;
			if (first_ctrl < 0)
				first_ctrl = i;
			last_ctrl = i;
			if (eq4(r->data, 0x02, 0, 0, 0))
				have_rst = 1;
		} else if (r->wval == 0x000c) { /* AUX command word */
			if (aux_n < 8)
				aux_seq[aux_n++] = r->data[0];
		} else if (r->wval == 0x0010) { /* AUX payload word0 */
			if (eq4(r->data, 0xff, 0xff, 0, 0))
				have_mask = 1;
			if (eq4(r->data, 0x05, 0x01, 0, 0))
				have_dac = 1;
			if (eq4(r->data, 0x02, 0, 0, 0)) {
				have_mode = 1;
				mode_write_idx = i;
			}
		}
	}

	/* Exactly STOP then RUN on R_CTRL, no RST on the capture path. */
	CHECK(ctrl_writes == 2);
	CHECK(first_ctrl >= 0 && eq4(mk.rec[first_ctrl].data, 0, 0, 0, 0));
	CHECK(last_ctrl >= 0 && eq4(mk.rec[last_ctrl].data, 0x01, 0, 0, 0));
	CHECK(!have_rst);
	/* Canonical AUX order: channel(1), rate(2), vref(3), pattern(5). */
	CHECK(aux_n == 4 && aux_seq[0] == 1 && aux_seq[1] == 2 &&
	      aux_seq[2] == 3 && aux_seq[3] == 5);
	CHECK(have_mask); /* (1<<16)-1 = ff ff 00 00 */
	CHECK(have_dac);  /* round(1.7/3.33/2*1024) = 261 = 05 01 00 00 */
	CHECK(have_mode); /* Emulation = 02 00 00 00 */
	CHECK(confirm_after_mode); /* confirm read-back present (section 6.7) */
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
	test_control_sequence();

	if (fails) {
		printf("%d check(s) FAILED\n", fails);
		return 1;
	}
	printf("all libslogic self-tests pass\n");
	return 0;
}
