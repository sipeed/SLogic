# SLogic driver plan: capture performance and support coverage

Status: proposed, 2026-09-16.

Scope: the two SLogic driver implementations in this workspace and the hosts
that consume them.

```text
sources/libsigrok/src/hardware/sipeed-slogic-analyzer/   Sipeed fork, branch slogic-dev
    api.c         1236 lines   model tables, config, USB, data shaping
    protocol.c     486 lines   transfer engine, session callback, stall rule
    protocol.h     120 lines   dev_context

sources/all-logic/libsigrok4DSL/hardware/sipeed-slogic/   ALL-LOGIC, branch main
    slogic16u3.c  2826 lines   model tables, USB, transfer engine, LA_CROSS_DATA conversion
```

Hosts: `pulseview`, `slogicview` and `sigrok-cli` consume `libsigrok`;
DSView inside `all-logic` consumes `libsigrok4DSL`.

## 1. Why this plan exists

The same USB protocol now has two independent implementations, and they have
already drifted apart in ways that are easy to get wrong:

- Channel-mode tables use opposite index orders: `all-logic` stores
  `{16, 8, 4}` while `libsigrok` stores `{4, 8, 16}`, with the samplerate
  limit tables aligned to each order. Cross-porting a change means
  re-indexing it by hand.
- Stall detection exists in both, in different forms. `libsigrok` commit
  `0c36240d` ("fix premature transfer timeout", taorye, 2026-07-24)
  introduced `timeout_count_limit`; `all-logic` then layered a stricter
  split on top (never-started vs data-flowing, plus a one-shot RUN retry)
  that was never offered back. `libsigrok` still treats a slow transfer as
  fatal on every transfer, which aborts a long capture any time the host
  consumer cannot keep up.
- The "drop the first 4 bytes" hardware workaround is implemented twice with
  different semantics: `all-logic` uses a `drop_left` state machine across
  transfers, `libsigrok` drops only on the first transfer (`first_here`).

Beyond drift, the two sides each hold something the other lacks (section 3),
and only one host/rate combination has been measured systematically
(section 2).

## 2. Baseline

Measured on Arch Linux, USB3, SLogic32U3 (`359F:3032`), with the ALL-LOGIC
driver. These numbers come from the work that produced
Doukeyi-X/ALL-LOGIC pull request #3.

| Metric | Measured |
| --- | --- |
| 32ch @ 200 MHz, 200 MSa, back-to-back | 48/48 full (47/48 on a second run), 1.27-1.35 s per capture |
| Sustained wire rate | ~793 MB/s (the link tops out at 800 MB/s for this mode) |
| Host conversion + snapshot append | ~670 MB/s |
| Device backpressure | starts after ~3 s, because the host is slower than the device |
| 1 s / 2 s / 4 s captures | 100% / 100% / 100% full; the 4 s run takes 4.85 s wall |
| GUI response during capture | ~5 ms average, down from ~200 ms |
| Reference `sigrok-cli` 1.1.0, same load | 15 of 30 runs wrote a 12-byte, 0-sample `FRAME-BEGIN`; with 1 s or 5 s gaps still only 6 of 12 |

Not measured yet: 16ch @ 400 MHz, 8ch @ 800 MHz, 4ch @ 1600 MHz, any USB2
port, captures longer than 4 s, and the same matrix on PulseView, SLogicView
and sigrok-cli.

## 3. Gap analysis

| Area | `libsigrok` (slogic-dev) | `all-logic` (main) |
| --- | --- | --- |
| Channel-mode order | `{4, 8, 16, 32}` ascending | `{16, 8, 4}` historical IDs |
| Stall rule | consecutive slow transfers abort, data flowing or not | never-started: consecutive rule + one RUN retry; data flowing: only 1 s of total silence is fatal |
| Transfer sizing | trained to the largest size that submits, target 250 ms per transfer | ~4 ms target, 32 KiB floor, 3 MiB cap, 16 transfers |
| Session source | `fd = -1 * libusb_ctx`, timeout `per_transfer_duration / 2`, one packet per iteration | `fd = -1`, timeout 1 ms, two packets per iteration |
| Data shaping | none needed: sample-major bytes go straight to `sr_session_send`, plus a byte expansion below 8 channels | must transpose to DSView `LA_CROSS_DATA`: 8x8 transpose, worker pool (half the cores, capped at 8), zero-copy fast path when a transfer is 64-sample aligned |
| First-transfer drop | 4 bytes, first transfer only | 4 bytes, `drop_left` state machine |
| Voltage threshold | `SR_CONF_VOLTAGE_THRESHOLD` as a `(dd)` tuple; the DAC is written with the average of the two values | single `SR_CONF_VTH` double |
| Trigger | driver-side soft trigger (`stl`) with a 10% pre-trigger ratio | none in the driver; DSView triggers in the host |
| Stop path | stop after transfers are freed, inside the session callback | stop deferred until every URB returns, retried up to 10 times with BUSY tolerance |
| Diagnostics | `sr_dbg` / `sr_spew` transfer lines | `-l4` register trace and a per-capture throughput line |
| Host-side fixes | - | session freewheel pacing, self-removing source, MCP socket lifetime |

## 4. The performance ceiling

Every top channel-mode rate hits the same link limit:

| Mode | Top rate | Wire rate |
| --- | --- | --- |
| 32ch | 200 MHz | 800 MB/s |
| 16ch | 400 MHz | 800 MB/s |
| 8ch | 800 MHz | 800 MB/s |
| 4ch | 1600 MHz | 800 MB/s |

800 MB/s is the ceiling; there is nothing to gain beyond it. The gap that
matters is on the host: conversion plus snapshot append runs at ~670 MB/s,
so the device throttles itself and the capture is limited by the host, not
by the analyzer. Every performance task below serves one goal:

> Keep the host above 800 MB/s end to end, so a long capture never
> backpressures the device.

## 5. Workstreams

### Phase 0 - one ruler, then a baseline (about one week)

Today each host is measured with different scripts, and only one
configuration has been measured at all. Build a host-agnostic benchmark
harness before changing any driver code.

- Generalize `sources/all-logic/tools/test_acceptance.py` and
  `test_config_persistence.py` into a harness that drives both transports:
  ALL-LOGIC over MCP, and `sigrok-cli` as a process.
- One JSON result per run plus a comparison table. Record at least: requested
  and captured samples, wall time, wire rate, host tail, process CPU, GUI
  response where measurable, and whether the analyzer backpressured
  (`USB link slower than the analyzer`).
- Run the full matrix: channel modes `{32, 16, 8, 4}` at their top rates,
  patterns `{Normal, USB connection test, Emulation}`, durations
  `{1, 2, 4, 10}` s, both transports, at least 10 repetitions per cell.
- Deliverable: the harness plus a baseline report committed under
  `build/docs/`.
- Exit criteria: numbers reproduce within +-3%, and the harness fails loudly
  when a capture comes back short.

### Phase 1 - host-side throughput (one to two weeks, largest gain)

Do not guess where the 670 MB/s cap sits: profile first, then attack the
bottleneck that shows up.

1. Profile the host path: transpose, snapshot append, datafeed plumbing.
2. Remove copies from the snapshot append path, or hand the converted buffer
   over without copying.
3. Make the transpose SIMD (the current 8x8 transpose is scalar 64-bit).
4. Drain adaptively: the session callback currently converts a fixed two
   packets per iteration, which falls behind during bursts.
5. Pool the USB transfer buffers instead of allocating and freeing one per
   transfer.
6. Sweep transfer sizes (4 ms today, 8/16/32 ms) and pick the throughput /
   stop-latency sweet spot with the Phase 0 harness.

- Exit criteria: 10 s at 32ch @ 200 MHz completes 100% with no backpressure
  warning, host tail under 50 ms, and stop-to-idle under 300 ms.
- The same work benefits `libsigrok` hosts only where the bottleneck is
  shared (transfer sizing, buffer pooling, session drain rate).

### Phase 2 - reliability (one to two weeks)

- Hot-plug: unhooking the device can abort DSView with a GLib
  `pthread_join` deadlock in `libsigrok4DSL/lib_main.c:close_device_instance()`,
  and after replugging, the device comes back `active:false` and needs a
  manual re-select. Fix both, and add an unplug/replug regression test.
- 32ch phase shift: a whole 32-bit word occasionally shifts by 16 bits
  (11 of 12 captures in one window, then not reproducible after a replug).
  Add a frame-alignment self-check using the Emulation pattern that records
  enough context to catch it, then root-cause it.
- USB2: measure the fallback path, which is currently only a static rate
  clamp with no measured data behind it.

### Phase 3 - feature parity and one source of truth (about two weeks)

Offer each side what the other has:

- To `libsigrok`: the layered stall rule with the one-shot RUN retry, the
  dynamic USB2 clamp, the transfer-size strategy if Phase 1 confirms it, the
  register trace option, and the shared harness.
- To `all-logic`: dual voltage threshold (`SR_CONF_VOLTAGE_THRESHOLD`), and
  driver-side soft trigger with pre-trigger.
- Write `slogic-protocol.md`: register map, AUX commands, model table,
  channel-mode ordering convention, packing rules, first-transfer drop
  semantics, stall rules. One page that both drivers cite.
- Add conformance vectors: same device and pattern, exported from both hosts,
  byte-compared after format normalization.

## 6. Acceptance metrics

| Metric | Target |
| --- | --- |
| Full-capture rate, whole matrix | >= 99% |
| Host sustained rate, 32ch @ 200 MHz | >= 800 MB/s, no backpressure warning |
| Long capture, 10 s | 100% captured, host tail < 50 ms |
| GUI response during capture | P95 < 20 ms |
| Stop to idle | < 300 ms |
| Hot-plug | no crash, device usable again without manual re-select |
| Cross-host data | identical after format normalization |

## 7. Risks and boundaries

- The 800 MB/s ceiling is hardware. Do not chase more.
- Device and firmware defects stay documented, not worked around: the
  reduced-channel modes send the high bytes of the 32-bit word (16ch to
  CH16-31, 8ch to CH24-31, 4ch to CH24-27), and the host reads little-endian
  low bits on purpose, matching the DSView U3Pro32 rule.
- All measurements so far are Linux x86_64 on a native package build. The
  workspace also builds linux-x86_64-musl, windows-x86_64-ucrt and
  macos-arm64; keep them building, and re-measure before quoting numbers for
  a release.
- `libsigrok` here is a product fork (`slogic-dev`) whose revisions are
  pinned by release tags. Coordinate before changing behavior a release
  depends on.
- A shared-core refactor would touch two different data models. Do it after
  Phase 1 and 2 have settled, and only with the conformance vectors in place.

## 8. Open decisions

1. Single source of truth: RESOLVED (2026-09-17, user decision) toward
   extraction — a shared `libslogic` source folder (USB data + control) that
   both front ends vendor a copy of, adapted with a thin porting layer, with
   the two data-shaping paths staying as adapters. The canonical protocol,
   drift resolutions, `libslogic` C API, and conformance-vector definition are
   specified in `slogic-protocol.md`. Sequence: freeze the spec → build
   conformance vectors from today's drivers → extract `libslogic` → port the
   libsigrok adapter first (byte-identical, release-pinned) → port the
   all-logic adapter → land Phase 1 buffer-pooling once in the core.
2. Where the harness lives: under `build/scripts/` next to the existing
   orchestration, or a new top-level development directory.
3. Who lands the `libsigrok` side of Phase 3: this workspace directly, or
   handed to the SLogic maintainers as patches.

## 9. References

- Driver implementations: `sources/libsigrok/src/hardware/sipeed-slogic-analyzer/`,
  `sources/all-logic/libsigrok4DSL/hardware/sipeed-slogic/slogic16u3.c`.
- Existing harness: `sources/all-logic/tools/test_acceptance.py`,
  `test_config_persistence.py`, `test_mcp_batch.py`,
  `test_mcp_gui_start_stop.py`.
- ALL-LOGIC driver work and measurements:
  `sources/all-logic/CHANGELOG.md`, section `Unreleased`.
- Pull request with the ALL-LOGIC side: Doukeyi-X/ALL-LOGIC#3.
- Reference timeout fix: `sources/libsigrok` commit `0c36240d`.
