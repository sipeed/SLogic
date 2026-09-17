# SLogic USB protocol: the canonical `libslogic` specification

Status: proposed, 2026-09-17.

This document is the single source of truth for how the host talks to a Sipeed
SLogic analyzer over USB — device model, control protocol, and the raw data
stream. It exists so the protocol lives in exactly one place, `libslogic`,
which both driver front ends vendor a copy of and adapt with a thin porting
layer instead of re-implementing.

It is derived by reading the two implementations that agree on the wire today:

```text
sources/libsigrok/src/hardware/sipeed-slogic-analyzer/{api,protocol}.c   (branch slogic-dev)
sources/all-logic/libsigrok4DSL/hardware/sipeed-slogic/slogic16u3.c      (branch main)
```

Where they agree, that behaviour is normative below. Where they drift, section
6 records the canonical choice and why. Nothing here changes the wire protocol;
it writes down what the firmware already expects.

Companion documents: `slogic-driver-plan.md` (the performance/coverage plan;
this spec resolves its section 8 open decision #1) and
`slogic-capture-baseline.md` (the Phase 0 measurement baseline).

---

## 1. Device model

| Product      | VID    | PID (run) | Bulk IN EP | Phys ch | Wire ceiling |
|--------------|--------|-----------|-----------|---------|--------------|
| SLogic Combo 8 | 0x359F | 0x0300 | 0x81 | 8  | 320 MHz·ch   |
| SLogic16U3     | 0x359F | 0x3031 | 0x82 | 16 | 3200 MHz·ch  |
| SLogic32U3     | 0x359F | 0x3032 | 0x82 | 32 | 6400 MHz·ch  |

DFU/bootloader PID is `0x30f1` (a distinct device; `libslogic` does not handle
firmware update). The Combo 8 speaks a small command protocol; the two U3
models share one register/AUX protocol (`SLOGIC_PROTO_U3`).

Interface 0 is claimed; there is one bulk IN endpoint and the vendor control
endpoint 0.

### Channel mode ↔ maximum samplerate

The firmware trades channel width for samplerate. This mapping is **physical
and order-independent** — `libslogic` stores it as `(channel_count →
max_rate)` pairs. The two front ends today store the same pairs in opposite
array order (section 6.1); the pairs themselves are identical.

| Model    | 4 ch      | 8 ch     | 16 ch    | 32 ch    |
|----------|-----------|----------|----------|----------|
| 16U3     | 800 MHz   | 400 MHz  | 200 MHz  | —        |
| 32U3     | 1600 MHz  | 800 MHz  | 400 MHz  | 200 MHz  |

Combo 8: 2 ch → 160 MHz, 4 ch → 80 MHz, 8 ch → 40 MHz.

On Windows the U3 ceilings are held one notch lower (16U3: 400/200/100;
`_WIN32` guard in both front ends) because the Windows USB stack cannot sustain
the top rate. `libslogic` exposes both the native and the Windows-capped table
and lets the adapter pick per build.

The advertised discrete samplerate list per model is the sorted set of
`SR_MHZ(n)` values in `samplerates_slogic16u3` / `_slogic32u3` /
`_slogiccombo8`; a requested rate is snapped to the nearest advertised rate not
exceeding the channel-mode ceiling.

---

## 2. Control protocol — U3 register map

Vendor control transfers, recipient device. Every register access is 32-bit,
one 4-byte `libusb_control_transfer` per word; multi-word payloads are issued
as consecutive words with `wValue = addr + offset`. Payload lengths are always
rounded up to a multiple of 4.

```
bmRequestType = LIBUSB_REQUEST_TYPE_VENDOR | LIBUSB_RECIPIENT_DEVICE | dir
bRequest      = 0x00 REG_READ  (dir = ENDPOINT_IN)
                0x01 REG_WRITE (dir = ENDPOINT_OUT)
wValue        = register address
wIndex        = 0
timeout       = 500 ms
```

| Register | Addr   | Meaning                                    |
|----------|--------|--------------------------------------------|
| R32_CTRL | 0x0004 | bit0 = RUN, bit1 = RST (write 0 = STOP)    |
| R32_FLAG | 0x0008 | status flags (read; unused by both drivers) |
| R32_AUX  | 0x000C | AUX mailbox header                         |
| —        | 0x0010 | AUX mailbox payload (`R32_AUX + 4`)        |

`RST` pulse = write `CTRL=0x02` then `CTRL=0x00`. `RUN` = write `CTRL=0x01`.
`STOP` = write `CTRL=0x00`. A capture start writes STOP/RUN plus config blocks
and **never** writes RST (which would discard pattern-generator and vref
setup).

### AUX mailbox transaction

Configuration goes through a mailbox at `R32_AUX`. One transaction:

1. **Write the command word** to `R32_AUX` (0x0C). Commands:
   `1 = channel mask`, `2 = samplerate`, `3 = vref`, `5 = test mode`.
2. **Poll the header** at `R32_AUX` until the ready bit is set:
   `(header >> 16) & 1 == 1`. Retry a small bounded number of times
   (libsigrok: 6, all-logic: 8) with the 500 ms per-word timeout, then fail.
3. **Payload length** in words comes from the header: `n = (header & 0xFFFF) >> 9`.
4. **Read the payload** from `R32_AUX + 4` (0x10), `n` words.
5. **Modify and write back** the payload to `R32_AUX + 4`.
6. **Read back** to confirm.

### Per-command payload semantics

- **Channel mask (cmd 1):** payload word 0 = `(1 << channel_count) - 1`
  (32 ch → 0xFFFFFFFF). Confirmed by read-back equality.
- **Samplerate (cmd 2):** the payload is `[uint16 base_idx][uint16 base_mhz]
  [uint32 divider]`. Walk `base_idx` until a base is found with
  `base_mhz*1e6 % want == 0`; on a miss, increment `base_idx`, write it back
  (4 bytes), and re-read. On a hit, write `divider = base/want - 1`.
- **Vref / threshold (cmd 3):** payload word 0 = DAC code.
  `dac = round(V / 3.33 / 2 * 1024)` (~10-bit against a 1.6 V reference).
  `V` is the mean of the two threshold values (both front ends drive a single
  averaged threshold today; the dual value is a libsigrok API artifact).
- **Test mode (cmd 5):** payload word 0 = mode. `0 = Normal`,
  `1 = USB connection test` (max-speed pattern), `2 = Emulation` (structured
  pattern generator). Selecting Normal on the U3 also issues an RST.

## 2b. Control protocol — Combo 8

No register map. A single vendor OUT command starts acquisition:

```
bRequest = 0xB1 (CMD_START), wValue = 0, wIndex = 0
payload  = [uint16 sample_rate_mhz little-endian][uint8 channel_count][pad]  (4 bytes)
```

`CMD_STOP` (0xB3) exists but is unreliable in current firmware; the documented
stop is to drain the bulk IN endpoint (read until a short/empty transfer).

---

## 3. Data path — bulk IN stream

Once `RUN` is set, the analyzer streams packed logic samples on the bulk IN
endpoint with **no framing or header**. The host submits a ring of bulk
transfers and processes them in order.

### Wire packing (sample-major)

Each sample is the parallel state of the enabled channels, LSB = D0:

| Channel mode | Bytes/sample | Packing                         |
|--------------|--------------|----------------------------------|
| 2 ch         | ¼            | 4 samples per byte               |
| 4 ch         | ½            | 2 samples per byte               |
| 8 ch         | 1            | 1 byte per sample                |
| 16 ch        | 2            | 2 little-endian bytes per sample |
| 32 ch        | 4            | 4 little-endian bytes per sample |

This raw sample-major stream is what `libslogic` delivers to the adapter. How
the adapter reshapes it (libsigrok byte-expansion for < 8 ch → `SR_DF_LOGIC`,
or all-logic transpose → `LA_CROSS_DATA` channel planes) is **not** part of
`libslogic` (section 5).

### First-transfer drop

The first 4 bytes of the stream are a hardware artifact and must be dropped
(`SLOGIC_DROP_FIRST_BYTES = 4`). Canonical implementation: a `drop_left`
counter initialised to 4, decremented across however many transfers it takes to
consume 4 bytes (section 6.3).

### Transfer sizing

Target one transfer ≈ a few hundred ms of data, aligned up to 32 KiB, with a
ring of up to 16 (`NUM_MAX_TRANSFERS = 16`). The reference sizing aims for
250 ms of data then quarters it so ≥ 4 transfers stay in flight; the bounds are
`[32 KiB, 3 MiB]`. Expected byte rate = `samplerate * channel_count / 8`.

### Stall / completion policy (canonical: section 6.2)

Per completed transfer, with `delta` = time since the previous completion and
`expected_us = transfer_size * 1e6 / expected_rate_bytes`:

- **Before any bytes arrive** (`raw_received_bytes == 0`): a transfer is "slow"
  when `delta > 1.3*expected_us` or `actual_rate < 0.7*expected_rate`. After
  `timeout_count_limit` (= number of submitted transfers) consecutive slow
  transfers the stream is considered "never started" — re-issue `RUN` once
  (RUN-swallow recovery), and if it still does not start, abort with an empty
  capture.
- **After bytes are flowing:** a slow transfer is only a one-shot warning
  ("draining at the host's pace") — legitimate USB backpressure when the host
  is the bottleneck (e.g. 32 ch @ 200 MHz). Only **complete silence** for
  `SLOGIC_STREAM_IDLE_US = 1_000_000` µs (1 s) is fatal.
- Any `LIBUSB_TRANSFER_STALL` / `OVERFLOW` / `NO_DEVICE` (or any non-timeout
  error status) aborts immediately.
- Completion: once `raw_received_bytes >= samples_need_bytes` (finite capture),
  clamp the last transfer and stop.

---

## 4. Proposed `libslogic` C API

`libslogic` depends only on `libusb.h` and its own headers — **never** on
`libsigrok.h` or `libsigrok4DSL`'s headers, because the two consumers ship
different, incompatible generations of those. It is a small vendored source
folder (`libslogic.c` + `libslogic.h`), copied verbatim into each consumer,
with a per-consumer adapter doing the framework glue.

```c
/* Transport: the host owns libusb; libslogic never opens or claims a device.
 * A mock transport (recorded traces) makes the control path testable without
 * hardware — this is what the conformance vectors drive. */
typedef struct {
    void *ctx;
    int (*control_write)(void *ctx, uint8_t req, uint16_t val, uint16_t idx,
                         const uint8_t *data, uint16_t len, unsigned timeout_ms);
    int (*control_read )(void *ctx, uint8_t req, uint16_t val, uint16_t idx,
                         uint8_t *data, uint16_t len, unsigned timeout_ms);
} slogic_transport;

/* Model table (channel↔rate pairs, EPs, ceilings) — read-only, order-free. */
const slogic_model *slogic_model_for_pid(uint16_t pid);

typedef struct {
    int      channel_count;   /* 2/4/8/16/32; adapter maps its mode index here */
    uint64_t samplerate_hz;
    double   threshold_v;
    int      pattern_mode;    /* 0 Normal, 1 USB test, 2 Emulation */
    int      windows_capped;  /* pick the _WIN32 ceiling table */
} slogic_config;

/* Control path (issues the register/AUX transactions of sections 2/2b). */
int slogic_reset    (slogic_dev *, const slogic_transport *);
int slogic_configure(slogic_dev *, const slogic_transport *, const slogic_config *);
int slogic_run      (slogic_dev *, const slogic_transport *);
int slogic_stop     (slogic_dev *, const slogic_transport *);

/* Transfer planning (section 3): size, count, per-transfer timeout, expected rate. */
typedef struct { uint32_t size; int count; uint64_t expected_rate_bytes;
                 unsigned timeout_ms; } slogic_transfer_plan;
int slogic_plan_transfers(const slogic_config *, slogic_transfer_plan *out);

/* Per-transfer shared post-processing. The adapter owns the libusb ring and
 * calls these; the raw (buf,len) it hands back is still sample-major — the
 * adapter shapes it. */
size_t slogic_apply_first_drop(slogic_stream *, uint8_t *buf, size_t len);

typedef enum { SLOGIC_STREAM_OK, SLOGIC_STREAM_WARN_SLOW,
               SLOGIC_STREAM_RETRY_RUN, SLOGIC_STREAM_ABORT } slogic_verdict;
slogic_verdict slogic_stream_watch(slogic_stream *, size_t got_bytes,
                                   int64_t now_us);
```

The adapter keeps everything framework-shaped: session/event-loop integration,
the config-key mapping (`SR_CONF_*` differs between the two libsigrok
generations), channel enable/disable, soft trigger (libsigrok only), and the
data reshape into `SR_DF_LOGIC` or `LA_CROSS_DATA`.

---

## 5. What stays in the adapter (explicitly out of scope for `libslogic`)

- **Data reshaping.** libsigrok: sample-major → `SR_DF_LOGIC`, expanding
  sub-byte modes so each sample occupies one byte. all-logic: bit-transpose to
  `LA_CROSS_DATA` 64-sample channel planes with a worker pool. Two data models;
  they do not merge.
- **Event loop.** libsigrok registers an `sr_session` source keyed off the
  libusb context; all-logic runs its own collect thread + `receive_data`.
- **Config surface.** `SR_CONF_NUM_LOGIC_CHANNELS` (count) vs
  `SR_CONF_CHANNEL_MODE` (mode index); different enum values across the two
  generations.
- **Soft trigger.** libsigrok has a driver-side `soft_trigger_logic`; all-logic
  has none. Trigger stays adapter-side.
- **Device discovery / claim / string descriptors / speed detection.**

---

## 6. Drift resolutions (canonical decisions)

### 6.1 Channel-mode table order — RESOLVED, cosmetic

libsigrok stores ascending `{4,8,16}`; all-logic descending `{16,8,4}`, each
with its limit table aligned. The `(channel_count → max_rate)` pairs are
identical. **Canonical:** `libslogic` stores order-free pairs; each adapter
presents them in whatever order its UI/config layer wants. The drift dissolves.

### 6.2 Stall policy — RESOLVED toward all-logic, pending baseline sign-off

libsigrok treats a slow transfer as fatal on *every* transfer, which truncates
long captures whenever the host is the bottleneck (observed: a 4 s request
ending at 621 MSa; and 32 false timeouts in the Phase 0 sweep). all-logic
reconciled this: rate-watchdog gates only the *never-started* case (+ one RUN
re-arm), and *mid-stream* only 1 s of complete silence is fatal. **Canonical:**
the all-logic reconciled policy (section 3). For libsigrok this is a behaviour
*improvement*, but libsigrok is release-pinned, so the migration keeps its
current rule until the conformance vectors and the Phase 0 baseline confirm the
new policy does not mask a real stall.

### 6.3 First-4-byte drop — RESOLVED toward all-logic

libsigrok drops 4 bytes only on the first transfer (`first_here`), assuming the
first transfer is ≥ 4 bytes; all-logic uses a `drop_left` counter that survives
a pathologically short first transfer. **Canonical:** the `drop_left` counter.

### 6.4 AUX poll retry count — RESOLVED

libsigrok retries 6, all-logic 8. **Canonical:** 8 (harmless headroom).

### 6.5 Transfer sizing math — RESOLVED

Keep the reference "250 ms then quarter, 32 KiB aligned, ≤ 16 in flight,
`[32 KiB, 3 MiB]`" (section 3). Any change is measured against the baseline
before landing.

---

## 7. Conformance vectors

The copies only stay honest if a mechanical check proves `libslogic` reproduces
the known-good wire behaviour byte-for-byte. Two layers:

1. **Control-sequence vectors.** For each `(model, config)` a golden trace of
   the exact control transfers `(bRequest, wValue, wIndex, data[4])` the
   configure/run/stop sequence emits. Generated by running `libslogic` against
   the **mock transport** (no hardware) and captured; regenerated from a real
   device with the driver's `-l4`/`sr_dbg` register trace to anchor the golden
   set. A byte diff fails the check.
2. **Packing vectors.** For each channel mode, a raw wire buffer plus the
   sample-major decode `libslogic` guarantees; the adapter reshape is then
   tested separately per host. These extend the Phase 0 harness
   (`build/bench/capture_bench.py`) `verify` subcommand.

The extraction sequence (see plan section 8): freeze this spec → build the
vectors from today's drivers → extract `libslogic` to satisfy them → port the
libsigrok adapter first (simpler data path, vectors must stay byte-identical
since it is release-pinned) → port the all-logic adapter → then land Phase 1
buffer-pooling once, in the core.
