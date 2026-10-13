# Changelog

All notable changes to the SLogic all-in-one build (PulseView + SLogicView +
sigrok-cli, plus ngscopeclient) are recorded here. Versions are published as
`release-X.Y.Z` tags; each platform archive is `SLogic-X.Y.Z-<platform>.zip`.

## v2.2.0 — 2026-10-13

### Highlights

- **AllLogic on Apple Silicon: capture length is no longer stuck at ~500 ms.** The
  capture-duration selector read an *uninitialized* software-depth value on arm64
  Macs — only x86 hosts were handled — so deep captures were impossible and the app
  could crash. Every 64-bit host now uses the full streaming depth; the ~500 ms
  ceiling is gone and the selectable length follows the real capture depth (tens of
  seconds at 200 MHz, much longer at lower rates), matching Windows/Linux.
- **ngscopeclient: deep captures no longer freeze.** Reshaping a capture into
  per-channel waveforms now picks a sparse or dense representation *per bit* and runs
  across worker threads with exact-size, reallocation-free buffers. A fast-toggling
  pattern (e.g. the Emulation counter) at hundreds of millions of samples used to
  grow single-threaded run-length vectors to tens of GB and hang the app; it now
  completes with bounded memory.

### Fixed

- **Correct throughput on the first (cold) capture.** The driver measures the average
  sample rate from the first received byte, excluding the firmware's cold-start /
  power-down wake-up (~7–8 ms). PulseView and the driver log now show the true rate on
  a first cold capture instead of an artificially low number.
- **SLogic32U3: first capture word no longer dropped.** Dropping the first 32-bit word
  is now a per-model quirk — kept for SLogic16U3 (still required by its firmware),
  removed for SLogic32U3 and Combo8 where current firmware emits a clean first word.

### Internal

- `sipeed-slogic-analyzer` keeps the bulk-IN pipe continuously busy by resubmitting
  each transfer before handing its buffer to the consumer thread.
- The regression self-test now **auto-detects the model** and covers **SLogic16U3** as
  well as 32U3 (per-model channel modes and aggregate standard), empirically probes the
  USB link generation on Windows (full 10G vs degraded 5G), and the checklist gained a
  step-by-step "download sigrok-cli → run" flow.
- The shared libslogic core (first-byte rate clock, per-model first-word drop) is kept
  byte-identical across all vendored copies.

## v2.1.0 — 2026-10-10

### Highlights

- **Windows capture throughput roughly doubled.** The `sipeed-slogic-analyzer`
  driver now enables WinUSB **RAW_IO** on its capture endpoint. Without it
  libusb's WinUSB backend keeps only one bulk-IN transfer in flight at a time, so
  Windows stalled at roughly half the USB-3 bandwidth. On a 10 Gbps link,
  sustained capture rose from **~420 MB/s to full ~800 MB/s** (matching Linux);
  the raw-link max-speed test reaches ~900 MB/s. No user action required — it
  needs a capable 10 Gbps host port and libusb ≥ 1.0.30 (bundled). Linux and
  macOS are unchanged.

### Added

- **ngscopeclient:** the SLogic digital **threshold is now editable as a single
  global comparator** (0–6 V) and applies to all D channels.
- **sigrok-cli-slogic plugin:** a thin, cross-platform `sigrok-cli` forwarder for
  driving SLogic from automation/agents (discover / capture / decode).

### Fixed

- **SLogicView (macOS):** combo-box drop-downs no longer middle-elide / truncate
  their text under the dark theme.

### Internal

- Added a cross-platform **SLogic32U3 regression self-test**
  (`build/bench/slogic_selftest.py`) plus its checklist: one run exercises the
  libsigrok capture + decode chain on Linux/macOS/Windows with *measured*
  throughput (not just completeness), a channel-mode clamp check, an open/close
  stress loop, and golden-`.sr` decode, and prints a paste-ready sign-off record.

## v2.0.0

Baseline all-in-one release: PulseView, SLogicView and sigrok-cli bundled per
platform (`SLogic-2.0.0-<platform>.zip`), with the `sipeed-slogic-analyzer`
driver and protocol decoders, plus ngscopeclient.
