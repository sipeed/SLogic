# Changelog

All notable changes to the SLogic all-in-one build (PulseView + SLogicView +
sigrok-cli, plus ngscopeclient) are recorded here. Versions are published as
`release-X.Y.Z` tags; each platform archive is `SLogic-X.Y.Z-<platform>.zip`.

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
