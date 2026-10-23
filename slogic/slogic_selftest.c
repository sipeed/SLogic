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
#include <stdlib.h>
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

	const slogic_model *u2 = slogic_model_for_pid(SLOGIC_PID_8U2);

	CHECK(c8 && strcmp(c8->name, "SLogic8U2") == 0);
	/* SLogic8U2: new PID 0x3000, no prefix (USB2 only); the old 0x0300
	 * firmware is the same model, named "(old) SLogic8U2" to prompt an update. */
	CHECK(u2 && u2->proto == SLOGIC_PROTO_COMBO8 && u2->max_bandwidth_hz == c8->max_bandwidth_hz);
	CHECK(u2 && !strcmp(u2->name, "SLogic8U2"));
	CHECK(!strcmp(slogic_name_tag(c8, SLOGIC_LINK_HIGH), "old"));
	{
		char b[64];
		CHECK(!strcmp(slogic_display_name(m32, SLOGIC_LINK_SUPER_PLUS, b, sizeof(b)), "(10G) SLogic32 U3"));
		CHECK(!strcmp(slogic_display_name(m16, SLOGIC_LINK_SUPER, b, sizeof(b)), "(5G) SLogic16 U3"));
		CHECK(!strcmp(slogic_display_name(u2, SLOGIC_LINK_HIGH, b, sizeof(b)), "(480M) SLogic8 U2"));
		CHECK(!strcmp(slogic_display_name(c8, SLOGIC_LINK_HIGH, b, sizeof(b)), "(old) SLogic8 U2"));
		CHECK(!strcmp(slogic_display_name(m32, SLOGIC_LINK_HIGH, b, sizeof(b)), "(480M) SLogic32 U3"));
		CHECK(!strcmp(slogic_display_name(m32, SLOGIC_LINK_UNKNOWN, b, sizeof(b)), "SLogic32 U3"));
	}
	CHECK(m16 && m16->pid == 0x3031 && m16->ep_in == 0x82);
	CHECK(m32 && m32->pid == 0x3032 && m32->physical_channels == 32);
	CHECK(slogic_model_for_pid(0x30f1) == NULL); /* DFU is not a runtime model */
	CHECK(slogic_model_for_pid(0x30f0) == NULL); /* 8U2 DFU either */
	CHECK(slogic_is_analyzer(0x359f, 0x3000) && slogic_is_analyzer(0x359f, 0x0300) &&
	      slogic_is_analyzer(0x359f, 0x3032) && !slogic_is_analyzer(0x359f, 0x30f2) &&
	      !slogic_is_analyzer(0x1a86, 0x3032));
	CHECK(slogic_models(&n) != NULL && n == 4);

	/* Ceilings: same physical mapping the two drivers agree on. */
	CHECK(slogic_max_rate(m16, 4) == SLOGIC_MHZ(800));
	CHECK(slogic_max_rate(m16, 8) == SLOGIC_MHZ(400));
	CHECK(slogic_max_rate(m16, 16) == SLOGIC_MHZ(200));
	CHECK(slogic_max_rate(m32, 4) == SLOGIC_MHZ(1400));
	CHECK(slogic_max_rate(m32, 32) == SLOGIC_MHZ(200));
	CHECK(slogic_max_rate(c8, 8) == SLOGIC_MHZ(40));
	CHECK(slogic_max_rate(m16, 5) == 0);  /* not a mode */
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

	/* Init leaves the drop at 0; the adapter seeds it from the model quirk
	 * (16U3 drops its partial first word, 32U3/Combo8 do not). */
	slogic_stream_init(&s, NULL, 0);
	CHECK(s.drop_left == 0);
	CHECK(slogic_model_for_pid(SLOGIC_PID_32U3)->first_drop_bytes == 0);
	s.drop_left = slogic_model_for_pid(SLOGIC_PID_16U3)->first_drop_bytes;
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

/* ---------------------------------------------------------------------- */
/* data layer: unpack, link caps, trigger, accounting, rate fit, report   */
/* ---------------------------------------------------------------------- */

static uint64_t rng_state = 0x9e3779b97f4a7c15ull;
static uint64_t rng(void)
{
	rng_state ^= rng_state << 13;
	rng_state ^= rng_state >> 7;
	rng_state ^= rng_state << 17;
	return rng_state;
}

static const int all_nch[] = { 2, 4, 8, 16, 32 };

static uint32_t smask_of(int nch)
{
	return nch >= 32 ? 0xffffffffu : ((1u << nch) - 1u);
}

/* Pack samples onto the wire (sample-major, earliest in the low bits). */
static uint8_t *pack(int nch, const uint32_t *v, size_t n, size_t *bytes)
{
	size_t nb = (size_t)slogic_bytes_for_samples(nch, n), i;
	uint8_t *p = calloc(nb ? nb : 1, 1);

	for (i = 0; i < n; i++) {
		if (nch < 8) {
			size_t spb = 8 / (size_t)nch;
			p[i / spb] |= (uint8_t)(v[i] << ((i % spb) * (size_t)nch));
		} else {
			unsigned u = (unsigned)nch / 8, k;
			for (k = 0; k < u; k++)
				p[i * u + k] = (uint8_t)(v[i] >> (8 * k));
		}
	}
	*bytes = nb;
	return p;
}

static uint32_t unit_get(const uint8_t *s, unsigned unit)
{
	uint32_t v = 0;
	unsigned k;

	for (k = 0; k < unit; k++)
		v |= (uint32_t)s[k] << (8 * k);
	return v;
}

static void test_unpack(void)
{
	size_t ci;

	CHECK(slogic_bytes_for_samples(4, 1001) == 501);
	CHECK(slogic_bytes_for_samples(4, 999) == 500);
	CHECK(slogic_bytes_for_samples(2, 5) == 2);
	CHECK(slogic_unitsize(4) == 1 && slogic_unitsize(8) == 1 &&
	      slogic_unitsize(16) == 2 && slogic_unitsize(32) == 4);

	for (ci = 0; ci < sizeof(all_nch) / sizeof(all_nch[0]); ci++) {
		int nch = all_nch[ci];
		unsigned unit = slogic_unitsize(nch);
		size_t n = 37, nb, i, first, len;
		uint32_t v[37];
		uint8_t *p, out[37 * 4];
		int ok = 1;

		for (i = 0; i < n; i++)
			v[i] = (uint32_t)rng() & smask_of(nch);
		p = pack(nch, v, n, &nb);
		/* Every (first, len) window, including partial trailing groups;
		 * the buffer is exactly ceil(n*nch/8) bytes (ASan catches overreads). */
		for (first = 0; first < n; first++)
			for (len = 0; first + len <= n; len++) {
				slogic_unpack_range(nch, p, first, len, out);
				for (i = 0; i < len; i++)
					if (unit_get(out + i * unit, unit) != v[first + i])
						ok = 0;
			}
		CHECK(ok);
		free(p);
	}
}

static void test_link_caps(void)
{
	const slogic_model *m32 = slogic_model_for_pid(SLOGIC_PID_32U3);
	const slogic_model *c8 = slogic_model_for_pid(SLOGIC_PID_COMBO8);
	uint64_t list[32];
	size_t n;

	CHECK(slogic_link_max_rate(m32, 4, SLOGIC_LINK_SUPER_PLUS) == SLOGIC_MHZ(1400));
	CHECK(slogic_link_max_rate(m32, 4, SLOGIC_LINK_UNKNOWN) == SLOGIC_MHZ(1400));
	CHECK(slogic_link_max_rate(m32, 4, SLOGIC_LINK_HIGH) == SLOGIC_MHZ(80));
	CHECK(slogic_link_max_rate(m32, 32, SLOGIC_LINK_HIGH) == SLOGIC_MHZ(10));
	CHECK(slogic_link_max_rate(c8, 8, SLOGIC_LINK_HIGH) == SLOGIC_MHZ(40));
	/* 32U3 on a 5G link: the 400 MB/s aggregate caps each mode. */
	CHECK(slogic_link_max_rate(m32, 4, SLOGIC_LINK_SUPER) == SLOGIC_MHZ(800));
	CHECK(slogic_link_max_rate(m32, 8, SLOGIC_LINK_SUPER) == SLOGIC_MHZ(400));
	CHECK(slogic_link_max_rate(m32, 16, SLOGIC_LINK_SUPER) == SLOGIC_MHZ(200));
	CHECK(slogic_link_max_rate(m32, 32, SLOGIC_LINK_SUPER) == SLOGIC_MHZ(100));
	CHECK(slogic_link_max_rate(m32, 4, SLOGIC_LINK_SUPER_PLUS) == SLOGIC_MHZ(1400));
	/* 16U3 is a 5G device: its native table already fits. */
	CHECK(slogic_link_max_rate(slogic_model_for_pid(SLOGIC_PID_16U3), 4,
				   SLOGIC_LINK_SUPER) == SLOGIC_MHZ(800));
	CHECK(slogic_pick_rate(m32, 4, SLOGIC_LINK_SUPER, SLOGIC_MHZ(1400), 1) == 0);
	CHECK(!strcmp(slogic_link_tag(SLOGIC_LINK_SUPER_PLUS), "10G") &&
	      !strcmp(slogic_link_tag(SLOGIC_LINK_SUPER), "5G") &&
	      slogic_link_tag(SLOGIC_LINK_UNKNOWN) == NULL);
	CHECK(slogic_pick_rate(m32, 4, SLOGIC_LINK_SUPER_PLUS, SLOGIC_MHZ(1400), 1) == SLOGIC_MHZ(1400));
	CHECK(slogic_pick_rate(m32, 4, SLOGIC_LINK_HIGH, SLOGIC_MHZ(1400), 1) == 0);
	CHECK(slogic_pick_rate(m32, 4, SLOGIC_LINK_HIGH, 0, 0) <= SLOGIC_MHZ(80));
	CHECK(slogic_pick_rate(m32, 4, SLOGIC_LINK_HIGH, 0, 0) > 0);
	n = slogic_rate_list(m32, 4, SLOGIC_LINK_HIGH, list, 32);
	CHECK(n > 0 && list[n - 1] <= SLOGIC_MHZ(80) && list[0] < list[n - 1]);
	n = slogic_rate_list(m32, 4, SLOGIC_LINK_SUPER_PLUS, list, 32);
	CHECK(n == m32->rate_count && list[n - 1] == SLOGIC_MHZ(1400));
	n = slogic_rate_list(m32, 4, SLOGIC_LINK_SUPER, list, 32);
	CHECK(n > 0 && list[n - 1] == SLOGIC_MHZ(800));
}

static int brute_trigger(const slogic_trigger_spec *sp, int nch,
			 const uint32_t *v, size_t n)
{
	size_t i;
	int c, edge = 0;

	for (c = 0; c < nch; c++)
		if (sp->match[c] >= SLOGIC_TRIG_RISING)
			edge = 1;
	for (i = edge ? 1 : 0; i < n; i++) {
		int ok = 1;
		for (c = 0; c < nch && ok; c++) {
			uint32_t s = (v[i] >> c) & 1, pv = i ? (v[i - 1] >> c) & 1 : 0;
			switch (sp->match[c]) {
			case SLOGIC_TRIG_ZERO: ok = !s; break;
			case SLOGIC_TRIG_ONE: ok = s; break;
			case SLOGIC_TRIG_RISING: ok = !pv && s; break;
			case SLOGIC_TRIG_FALLING: ok = pv && !s; break;
			case SLOGIC_TRIG_EDGE: ok = pv != s; break;
			default: break;
			}
		}
		if (ok)
			return (int)i;
	}
	return -1;
}

static void test_trigger(void)
{
	size_t ci;
	int bad = 0, round;

	for (ci = 0; ci < sizeof(all_nch) / sizeof(all_nch[0]); ci++) {
		int nch = all_nch[ci];
		unsigned wu = nch >= 8 ? (unsigned)nch / 8 : 0;
		for (round = 0; round < 60; round++) {
			size_t n = 3000, i, nb, off;
			uint32_t *v = malloc(n * sizeof(*v));
			uint8_t *p;
			slogic_trigger_spec sp;
			slogic_trigger t;
			int64_t got = -1;
			int want, kind = round % 6;
			int ch_a = (int)(rng() % (uint64_t)nch);
			int ch_b = (int)((ch_a + 1) % nch);

			/* Slowly toggling random lines (edges are rare). */
			v[0] = (uint32_t)rng() & smask_of(nch);
			for (i = 1; i < n; i++) {
				uint32_t flip = (rng() % 97 == 0) ? (uint32_t)rng() : 0;
				v[i] = (v[i - 1] ^ flip) & smask_of(nch);
			}
			memset(&sp, 0, sizeof(sp));
			switch (kind) {
			case 0: sp.match[ch_a] = SLOGIC_TRIG_RISING; break;
			case 1: sp.match[ch_a] = SLOGIC_TRIG_FALLING; break;
			case 2: sp.match[ch_a] = SLOGIC_TRIG_EDGE; break;
			case 3: sp.match[ch_a] = SLOGIC_TRIG_RISING;
				sp.match[ch_b] = SLOGIC_TRIG_ONE; break;
			case 4: sp.match[ch_a] = SLOGIC_TRIG_ONE;
				sp.match[ch_b] = SLOGIC_TRIG_ZERO; break;
			default: sp.match[nch - 1] = SLOGIC_TRIG_EDGE; break;
			}
			want = brute_trigger(&sp, nch, v, n);
			p = pack(nch, v, n, &nb);
			slogic_trigger_compile(&t, &sp, nch);
			/* Feed in random chunks so edges straddle buffer ends. */
			for (off = 0; off < nb && got < 0;) {
				size_t len = 1 + (size_t)(rng() % 700), base;
				if (off + len > nb)
					len = nb - off;
				if (wu)
					len -= len % wu;
				if (!len)
					len = wu ? wu : 1;
				base = wu ? off / wu : off * (8 / (size_t)nch);
				got = slogic_trigger_scan(&t, p + off, len, 0);
				if (got >= 0)
					got += (int64_t)base;
				off += len;
			}
			if (got != want) {
				if (!bad)
					printf("  trigger nch=%d kind=%d want %d got %lld\n",
					       nch, kind, want, (long long)got);
				bad++;
			}
			free(p);
			free(v);
		}
	}
	CHECK(bad == 0);

	{ /* A channel outside the current mode is rejected. */
		slogic_trigger_spec sp;
		slogic_trigger t;
		memset(&sp, 0, sizeof(sp));
		sp.match[9] = SLOGIC_TRIG_RISING;
		CHECK(slogic_trigger_compile(&t, &sp, 8) == SLOGIC_ERR_ARG);
		CHECK(slogic_trigger_compile(&t, &sp, 16) == SLOGIC_OK);
	}
}

struct collect {
	uint32_t *v;
	size_t n, cap;
	int64_t trig;
	size_t stop_after;
};

static int collect_data(void *user, const uint8_t *s, size_t n, unsigned unit)
{
	struct collect *c = user;
	size_t i;

	for (i = 0; i < n && c->n < c->cap; i++)
		c->v[c->n++] = unit_get(s + i * unit, unit);
	return c->stop_after && c->n >= c->stop_after;
}

static void collect_trigger(void *user, uint64_t idx)
{
	((struct collect *)user)->trig = (int64_t)idx;
}

/* Feed a counter pattern of n samples through an accumulator in random chunk
 * sizes and collect what is delivered. */
static int run_acc(int nch, uint64_t limit, const slogic_trigger_spec *sp,
		   uint64_t pre, unsigned drop, size_t n, struct collect *c,
		   size_t stop_after)
{
	uint32_t *v = malloc(n * sizeof(*v));
	size_t i, nb, off;
	uint8_t *p;
	slogic_acc a;
	slogic_sink sink = { c, collect_data, collect_trigger };
	int r = SLOGIC_ACC_MORE;

	for (i = 0; i < n; i++)
		v[i] = (uint32_t)i & smask_of(nch);
	p = pack(nch, v, n, &nb);
	memset(c, 0, sizeof(*c));
	c->cap = n + 16;
	c->v = malloc(c->cap * sizeof(uint32_t));
	c->trig = -1;
	c->stop_after = stop_after;
	if (slogic_acc_init(&a, nch, limit, sp, pre, drop, &sink) != SLOGIC_OK)
		return -99;
	for (off = 0; off < nb && r == SLOGIC_ACC_MORE;) {
		size_t len = 1 + (size_t)(rng() % 900);
		if (off + len > nb)
			len = nb - off;
		r = slogic_acc_feed(&a, p + off, len);
		off += len;
	}
	slogic_acc_free(&a);
	free(p);
	free(v);
	return r;
}

static int seq_ok(const struct collect *c, uint32_t from, int nch)
{
	size_t i;

	for (i = 0; i < c->n; i++)
		if (c->v[i] != ((from + (uint32_t)i) & smask_of(nch)))
			return 0;
	return 1;
}

static void test_acc(void)
{
	size_t ci;
	struct collect c;
	slogic_trigger_spec sp;
	int r;

	for (ci = 0; ci < sizeof(all_nch) / sizeof(all_nch[0]); ci++) {
		int nch = all_nch[ci];
		uint32_t dropped = (uint32_t)(4 * 8 / nch);

		/* Exact odd limits (firmware team H1/H2: 4ch n=999/1001/1002). */
		r = run_acc(nch, 1001, NULL, 0, 0, 5000, &c, 0);
		CHECK(r == SLOGIC_ACC_DONE && c.n == 1001 && seq_ok(&c, 0, nch));
		free(c.v);
		r = run_acc(nch, 999, NULL, 0, 0, 5000, &c, 0);
		CHECK(r == SLOGIC_ACC_DONE && c.n == 999 && seq_ok(&c, 0, nch));
		free(c.v);
		/* Not enough data: everything delivered, still MORE. */
		r = run_acc(nch, 4000, NULL, 0, 0, 1004, &c, 0);
		CHECK(r == SLOGIC_ACC_MORE && c.n == 1004 && seq_ok(&c, 0, nch));
		free(c.v);
		/* First-word drop of 4 bytes. */
		r = run_acc(nch, 100, NULL, 0, 4, 5000, &c, 0);
		CHECK(r == SLOGIC_ACC_DONE && c.n == 100 && seq_ok(&c, dropped, nch));
		free(c.v);
		/* Sink asks to stop. */
		r = run_acc(nch, 0, NULL, 0, 0, 5000, &c, 300);
		CHECK(r == SLOGIC_ACC_DONE && c.n >= 300);
		free(c.v);

		/* Trigger arms after the pre-trigger window fills: rising edge of
		 * bit 1 (every 4 samples from 2) with pre 10 -> trigger at sample 10,
		 * delivered stream starts at sample 0. */
		memset(&sp, 0, sizeof(sp));
		sp.match[1] = SLOGIC_TRIG_RISING;
		r = run_acc(nch, 100, &sp, 10, 0, 5000, &c, 0);
		CHECK(r == SLOGIC_ACC_DONE && c.n == 100 && c.trig == 10 &&
		      seq_ok(&c, 0, nch));
		free(c.v);
		/* Late edge on the top bit: first rise at or after the window. */
		memset(&sp, 0, sizeof(sp));
		{
			int b = nch >= 8 ? 7 : nch - 1;
			uint32_t m = smask_of(nch), at = 10, prev, cur;
			sp.match[b] = SLOGIC_TRIG_RISING;
			for (;; at++) {
				prev = ((at - 1) & m) >> b & 1;
				cur = (at & m) >> b & 1;
				if (!prev && cur)
					break;
			}
			r = run_acc(nch, 100, &sp, 10, 0, 5000, &c, 0);
			CHECK(r == SLOGIC_ACC_DONE && c.n == 100 && c.trig == 10 &&
			      seq_ok(&c, at - 10, nch));
			free(c.v);
			/* Continuous + trigger: pre then everything after. */
			r = run_acc(nch, 0, &sp, 10, 0, 3000, &c, 0);
			CHECK(r == SLOGIC_ACC_MORE && c.trig == 10 &&
			      c.n == 3000 - (at - 10) && seq_ok(&c, at - 10, nch));
			free(c.v);
		}
		/* Firmware-team baseline: n=100000, 10% -> trigger at 10000. */
		memset(&sp, 0, sizeof(sp));
		sp.match[0] = SLOGIC_TRIG_RISING;
		r = run_acc(nch, 100000, &sp, 10000, 0, 120000, &c, 0);
		CHECK(r == SLOGIC_ACC_DONE && c.n == 100000 && c.trig == 10000 &&
		      (c.v[10000] & 1) && !(c.v[9999] & 1));
		free(c.v);
		/* Trigger never fires: nothing delivered. */
		memset(&sp, 0, sizeof(sp));
		sp.match[0] = SLOGIC_TRIG_RISING;
		sp.match[1] = SLOGIC_TRIG_FALLING; /* never at the same sample */
		r = run_acc(nch, 100, &sp, 10, 0, 3000, &c, 0);
		CHECK(r == SLOGIC_ACC_MORE && c.n == 0 && c.trig == -1);
		free(c.v);
	}
}

static void test_ratefit(void)
{
	static const uint64_t sizes[] = { 65536, 2752512, 50000000 };
	size_t si;
	slogic_ratefit f;
	double mbps = 0, cold = 0;

	for (si = 0; si < 3; si++) {
		uint64_t s = sizes[si], total = 0;
		const double rate = 800.0; /* bytes/us */
		int k;
		/* RUN at t=1000 us, data starts 7.5 ms later, 400 MB. */
		slogic_ratefit_init(&f, 1000);
		for (k = 1; total < 400000000ull || k < 4; k++) {
			total += s;
			slogic_ratefit_add(&f, 1000 + 7500 + (int64_t)(total / rate), s);
		}
		CHECK(slogic_ratefit_get(&f, &mbps, &cold) == SLOGIC_OK);
		CHECK(mbps > rate * 0.999 && mbps < rate * 1.001);
		CHECK(cold > 7.45 && cold < 7.55);
	}
	/* Event-loop batching: completions reaped in pairs share a timestamp. */
	{
		uint64_t s = 2752512, total = 0;
		int k;
		slogic_ratefit_init(&f, 0);
		for (k = 1; k <= 200; k++) {
			int64_t t;
			total += s;
			t = (int64_t)((total + (k % 2 ? s : 0)) / 800.0);
			slogic_ratefit_add(&f, t, s);
		}
		CHECK(slogic_ratefit_get(&f, &mbps, NULL) == SLOGIC_OK);
		CHECK(mbps > 792.0 && mbps < 808.0);
	}
	/* Not enough points. */
	slogic_ratefit_init(&f, 0);
	slogic_ratefit_add(&f, 100, 4096);
	CHECK(slogic_ratefit_get(&f, &mbps, &cold) != SLOGIC_OK);
	slogic_ratefit_add(&f, 100, 4096); /* same time: no slope */
	CHECK(slogic_ratefit_get(&f, &mbps, &cold) != SLOGIC_OK);
}

static void test_report_format(void)
{
	slogic_report r;
	char buf[512];

	memset(&r, 0, sizeof(r));
	r.end = SLOGIC_END_OK;
	r.model = "SLogic8U2";
	r.nch = 8;
	r.samplerate_hz = SLOGIC_MHZ(40);
	r.samples = r.limit = 1000;
	r.mbps = 39.9;
	r.fit_n = 5;
	slogic_report_format(&r, buf, sizeof(buf));
	CHECK(strncmp(buf, "slogic-report v1 model=SLogic8U2 ch=8 rate_mhz=40 end=ok ", 57) == 0);
	CHECK(strstr(buf, " samples=1000/1000 ") && strstr(buf, " mbps=39.9 ") &&
	      strstr(buf, " trig=none "));
	r.end = SLOGIC_END_ERROR;
	r.reason = "stall";
	r.fit_n = 1;
	r.triggered = 1;
	r.trig_index = 10;
	r.pre = 10;
	slogic_report_format(&r, buf, sizeof(buf));
	CHECK(strstr(buf, " end=error:stall ") && strstr(buf, " mbps=nan ") &&
	      strstr(buf, " trig=at:10,pre:10 "));
}


/* Combo 8 start: [rate MHz lo][rate MHz hi][channels][pattern], one vendor OUT 0xB1. */
static void test_combo8_start(void)
{
	struct mock_ctx mk;
	slogic_transport t;
	slogic_config c;

	memset(&mk, 0, sizeof(mk));
	t.ctx = &mk;
	t.control_write = mock_cw;
	t.control_read = mock_cr;
	memset(&c, 0, sizeof(c));
	c.channel_count = 4;
	c.samplerate_hz = SLOGIC_MHZ(320);
	c.pattern_mode = SLOGIC_PATTERN_EMULATION;
	CHECK(slogic_run(slogic_model_for_pid(SLOGIC_PID_COMBO8), &t, &c) == SLOGIC_OK);
	CHECK(mk.n == 1 && !mk.rec[0].is_read && mk.rec[0].req == 0xb1);
	CHECK(eq4(mk.rec[0].data, 0x40, 0x01, 4, SLOGIC_PATTERN_EMULATION));

	/* Normal mode keeps the byte older firmware has always seen: 0. */
	memset(&mk, 0, sizeof(mk));
	c.pattern_mode = SLOGIC_PATTERN_NORMAL;
	CHECK(slogic_run(slogic_model_for_pid(SLOGIC_PID_COMBO8), &t, &c) == SLOGIC_OK);
	CHECK(eq4(mk.rec[0].data, 0x40, 0x01, 4, 0));
}

/*
 * Sample clock base selection against a device with the SLogic32U3's measured
 * layout: slot 0 = 1400 MHz, slot 1 = 800 MHz, slots 2-3 empty, the selected
 * slot remembered across configurations (the index is masked to 2 bits).
 */
struct clock_mock {
	uint8_t last_cmd;
	uint16_t sel;
	uint32_t divm1;
};

static const uint16_t clock_bases[4] = { 1400, 800, 0, 0 };

static int clock_cw(void *ctx, uint8_t req, uint16_t wval, uint16_t widx,
		    const uint8_t *data, uint16_t len, unsigned to)
{
	struct clock_mock *m = ctx;
	(void)req; (void)widx; (void)to;
	if (wval == 0x000c)
		m->last_cmd = data[0];
	else if (wval == 0x0010 && m->last_cmd == 0x02)
		m->sel = (uint16_t)((data[0] | (data[1] << 8)) & 3);
	else if (wval == 0x0014 && m->last_cmd == 0x02)
		m->divm1 = (uint32_t)data[0] | ((uint32_t)data[1] << 8) |
			   ((uint32_t)data[2] << 16) | ((uint32_t)data[3] << 24);
	return len;
}

static int clock_cr(void *ctx, uint8_t req, uint16_t wval, uint16_t widx,
		    uint8_t *data, uint16_t len, unsigned to)
{
	struct clock_mock *m = ctx;
	uint32_t w = 0;
	(void)req; (void)widx; (void)to;
	if (wval == 0x000c)
		w = (1u << 16) | (((m->last_cmd == 0x02 ? 8u : 4u) << 9) & 0xffffu);
	else if (wval == 0x0010 && m->last_cmd == 0x02)
		w = (uint32_t)m->sel | ((uint32_t)clock_bases[m->sel] << 16);
	else if (wval == 0x0014 && m->last_cmd == 0x02)
		w = m->divm1;
	memset(data, 0, len);
	data[0] = (uint8_t)w;
	data[1] = (uint8_t)(w >> 8);
	data[2] = (uint8_t)(w >> 16);
	data[3] = (uint8_t)(w >> 24);
	return len;
}

static int clock_configure(struct clock_mock *m, uint64_t rate, unsigned base)
{
	slogic_transport t = { .ctx = m, .control_write = clock_cw, .control_read = clock_cr };
	slogic_config c = { .channel_count = 8, .samplerate_hz = rate, .threshold_v = 1.6,
			    .clock_base_mhz = base };
	return slogic_configure(slogic_model_for_pid(SLOGIC_PID_32U3), &t, &c);
}

static void test_clock_base(void)
{
	struct clock_mock m = { 0 };

	/* Default: 800 MHz first, from slot 0 (where CTRL=RST leaves it) or slot 1. */
	m.sel = 0;
	CHECK(clock_configure(&m, SLOGIC_MHZ(200), 0) == SLOGIC_OK);
	CHECK(m.sel == 1 && m.divm1 == 3);              /* 800 / 4, not 1400 / 7 */
	m.sel = 0;
	CHECK(clock_configure(&m, SLOGIC_MHZ(5), 0) == SLOGIC_OK);
	CHECK(m.sel == 1 && m.divm1 == 159);
	CHECK(clock_configure(&m, SLOGIC_MHZ(400), 0) == SLOGIC_OK);
	CHECK(m.sel == 1 && m.divm1 == 1);              /* 800 / 2 */
	/* Only 1400 MHz falls back, wrapping past the empty slots. */
	CHECK(clock_configure(&m, SLOGIC_MHZ(1400), 0) == SLOGIC_OK);
	CHECK(m.sel == 0 && m.divm1 == 0);
	CHECK(clock_configure(&m, SLOGIC_MHZ(200), 0) == SLOGIC_OK);
	CHECK(m.sel == 1 && m.divm1 == 3);

	/* Required base: 200 MHz is forced onto the 800 MHz PLL. */
	m.sel = 0;
	CHECK(clock_configure(&m, SLOGIC_MHZ(200), 800) == SLOGIC_OK);
	CHECK(m.sel == 1 && m.divm1 == 3);              /* 800 / 4 */
	CHECK(clock_configure(&m, SLOGIC_MHZ(5), 800) == SLOGIC_OK);
	CHECK(m.sel == 1 && m.divm1 == 159);
	/* A rate the required base cannot make is refused. */
	CHECK(clock_configure(&m, SLOGIC_MHZ(1400), 800) == SLOGIC_ERR_ARG);
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
	test_combo8_start();
	test_clock_base();
	test_unpack();
	test_link_caps();
	test_trigger();
	test_acc();
	test_ratefit();
	test_report_format();

	if (fails) {
		printf("%d check(s) FAILED\n", fails);
		return 1;
	}
	printf("all libslogic self-tests pass\n");
	return 0;
}
