/*
 * libslogic — shared USB core for Sipeed SLogic logic analyzers.
 *
 * Copyright (C) 2023-2025 Shenzhen Sipeed Technology Co., Ltd.
 * (深圳市矽速科技有限公司) <support@sipeed.com>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.  See <http://www.gnu.org/licenses/>.
 *
 * Model registry, channel-mode ceilings, transfer planning, and the shared
 * per-transfer post-processing (first-byte drop and the stall watchdog). The
 * register/AUX control path (slogic_reset/configure/run/stop) is implemented in
 * a following commit, verified against build/bench/slogic_control_vectors.py.
 * Behaviour is specified in build/docs/slogic-protocol.md.
 */

#include "slogic.h"

#include <string.h>

/* -------------------- model registry -------------------- */

extern const slogic_model slogic_model_16u3; /* slogic16u3.c */
extern const slogic_model slogic_model_32u3; /* slogic32u3.c */

/* Combo 8 is the small legacy command protocol; its table lives here. */
static const uint64_t rates_combo8[] = {
	SLOGIC_MHZ(1),  SLOGIC_MHZ(2),  SLOGIC_MHZ(4),  SLOGIC_MHZ(5),
	SLOGIC_MHZ(8),  SLOGIC_MHZ(10), SLOGIC_MHZ(16), SLOGIC_MHZ(20),
	SLOGIC_MHZ(32), SLOGIC_MHZ(40), SLOGIC_MHZ(80), SLOGIC_MHZ(160),
};

/* 2 ch -> 160, 4 ch -> 80, 8 ch -> 40 MHz. */
static const slogic_rate_limit limits_combo8[] = {
	{ 2, SLOGIC_MHZ(160) },
	{ 4, SLOGIC_MHZ(80) },
	{ 8, SLOGIC_MHZ(40) },
};

static const slogic_model slogic_model_combo8 = {
	.name = "SLogic Combo 8",
	.pid = SLOGIC_PID_COMBO8,
	.ep_in = 0x81,
	.physical_channels = 8,
	.proto = SLOGIC_PROTO_COMBO8,
	.max_bandwidth_hz = SLOGIC_MHZ(320),
	.rates = rates_combo8,
	.rate_count = sizeof(rates_combo8) / sizeof(rates_combo8[0]),
	.limits = limits_combo8,
	.limits_win = NULL,
	.limit_count = sizeof(limits_combo8) / sizeof(limits_combo8[0]),
};

static const slogic_model *const registry[] = {
	&slogic_model_combo8,
	&slogic_model_16u3,
	&slogic_model_32u3,
};

const slogic_model *const *slogic_models(size_t *count)
{
	if (count)
		*count = sizeof(registry) / sizeof(registry[0]);
	return registry;
}

const slogic_model *slogic_model_for_pid(uint16_t pid)
{
	size_t i;

	for (i = 0; i < sizeof(registry) / sizeof(registry[0]); i++) {
		if (registry[i]->pid == pid)
			return registry[i];
	}
	return NULL;
}

uint64_t slogic_max_rate(const slogic_model *m, int channel_count, int windows)
{
	const slogic_rate_limit *tbl;
	size_t i;

	if (!m)
		return 0;
	tbl = (windows && m->limits_win) ? m->limits_win : m->limits;
	for (i = 0; i < m->limit_count; i++) {
		if (tbl[i].channels == channel_count)
			return tbl[i].max_rate_hz;
	}
	return 0;
}

/* -------------------- transfer planning -------------------- */

#define SLOGIC_ALIGN     (32u * 1024u)
#define SLOGIC_SIZE_MIN  (32u * 1024u)
#define SLOGIC_SIZE_MAX  (3u * 1024u * 1024u)
#define SLOGIC_TOLERANCE 0.30

static uint32_t align_up(uint32_t v, uint32_t a)
{
	return (v + (a - 1)) & ~(a - 1);
}

int slogic_plan_transfers(const slogic_config *c, slogic_sizing sizing,
			  slogic_transfer_plan *out)
{
	uint64_t rate_bytes;
	uint32_t size;
	uint64_t duration_ms;

	if (!c || !out || c->channel_count <= 0 || c->samplerate_hz == 0)
		return SLOGIC_ERR_ARG;

	rate_bytes = c->samplerate_hz * (uint64_t)c->channel_count / 8u;
	if (rate_bytes == 0)
		return SLOGIC_ERR_ARG;

	if (sizing == SLOGIC_SIZING_LIBSIGROK) {
		/* 250 ms target, 32 KiB aligned, quartered so >= 4 are in flight
		 * (protocol.md section 3). No upper cap in the reference; we keep
		 * the floor so a tiny/very-slow capture still submits. */
		uint64_t bytes_250ms = rate_bytes / 4u; /* 250 ms */
		size = align_up((uint32_t)(bytes_250ms > 0xffffffffu ?
					   0xffffffffu : bytes_250ms),
				SLOGIC_ALIGN);
		size >>= 2;
		if (size < SLOGIC_SIZE_MIN)
			size = SLOGIC_SIZE_MIN;
	} else {
		/* ~4 ms target, clamp [32 KiB, 3 MiB] (protocol.md section 3). */
		uint64_t bytes_4ms = rate_bytes * 4u / 1000u;
		if (bytes_4ms < SLOGIC_SIZE_MIN)
			bytes_4ms = SLOGIC_SIZE_MIN;
		if (bytes_4ms > SLOGIC_SIZE_MAX)
			bytes_4ms = SLOGIC_SIZE_MAX;
		size = align_up((uint32_t)bytes_4ms, SLOGIC_ALIGN);
		if (size > SLOGIC_SIZE_MAX)
			size = SLOGIC_SIZE_MAX;
	}

	duration_ms = (uint64_t)size * 1000u / rate_bytes;
	if (duration_ms == 0)
		duration_ms = 1;

	out->size_bytes = size;
	out->ring_count = SLOGIC_MAX_TRANSFERS;
	out->expected_rate_bytes = rate_bytes;
	/* Match the resubmit timeout: (tolerance+1) * duration * 4, floored. */
	out->timeout_ms = (unsigned)((SLOGIC_TOLERANCE + 1.0) * duration_ms * 4.0);
	if (out->timeout_ms < 10)
		out->timeout_ms = 10;
	return SLOGIC_OK;
}

/* -------------------- per-transfer post-processing -------------------- */

void slogic_stream_init(slogic_stream *s, const slogic_transfer_plan *p,
			uint64_t need_bytes)
{
	if (!s)
		return;
	memset(s, 0, sizeof(*s));
	s->drop_left = 4; /* first-transfer 4-byte hardware artifact (section 3) */
	s->need_bytes = need_bytes;
	if (p) {
		s->slow_limit = (unsigned)(p->ring_count > 0 ? p->ring_count : 1);
		s->expected_rate_bytes = (uint32_t)p->expected_rate_bytes;
		s->transfer_size = p->size_bytes;
	} else {
		s->slow_limit = 1;
	}
}

size_t slogic_apply_first_drop(slogic_stream *s, uint8_t *buf, size_t len)
{
	size_t drop;

	if (!s || s->drop_left <= 0 || !buf || len == 0)
		return len;
	drop = ((size_t)s->drop_left < len) ? (size_t)s->drop_left : len;
	memmove(buf, buf + drop, len - drop);
	s->drop_left -= (int)drop;
	return len - drop;
}

slogic_verdict slogic_stream_watch(slogic_stream *s, size_t got_bytes,
				   int64_t now_us, int64_t since_last_us)
{
	double expected_us, actual_rate;
	int slow;

	if (!s)
		return SLOGIC_STREAM_ABORT;

	if (s->time_start_us == 0)
		s->time_start_us = now_us;
	if (got_bytes > 0) {
		s->received_bytes += got_bytes;
		s->time_last_data_us = now_us;
	}

	if (s->need_bytes && s->received_bytes >= s->need_bytes)
		return SLOGIC_STREAM_DONE;

	/* Not enough history to judge speed yet. */
	if (since_last_us <= 0 || s->expected_rate_bytes == 0 ||
	    s->transfer_size == 0)
		return SLOGIC_STREAM_OK;

	expected_us = (double)s->transfer_size * 1000000.0 /
		      (double)s->expected_rate_bytes;
	actual_rate = (double)got_bytes * 1000000.0 / (double)since_last_us;
	slow = ((double)since_last_us > (SLOGIC_TOLERANCE + 1.0) * expected_us) ||
	       (actual_rate < (1.0 - SLOGIC_TOLERANCE) *
				      (double)s->expected_rate_bytes);

	if (s->received_bytes == 0) {
		/* Stream has not started: the rate watchdog is authoritative. */
		if (slow)
			s->slow_count++;
		else
			s->slow_count = 0;
		if (s->slow_count >= s->slow_limit) {
			if (!s->run_retried) {
				/* Firmware swallowed RUN — re-arm exactly once. */
				s->run_retried = 1;
				s->slow_count = 0;
				return SLOGIC_STREAM_RETRY_RUN;
			}
			return SLOGIC_STREAM_ABORT;
		}
		return SLOGIC_STREAM_OK;
	}

	/* Data is flowing: only total silence is fatal; slow-but-alive is
	 * legitimate host backpressure and warns once (protocol.md 6.2). */
	{
		int64_t idle_us = (s->time_last_data_us ? s->time_last_data_us
						       : s->time_start_us);
		idle_us = now_us - idle_us;
		if (idle_us > SLOGIC_STREAM_IDLE_US)
			return SLOGIC_STREAM_ABORT;
	}
	if (slow && !s->slow_warned) {
		s->slow_warned = 1;
		return SLOGIC_STREAM_WARN_SLOW;
	}
	return SLOGIC_STREAM_OK;
}
