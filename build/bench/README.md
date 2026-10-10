# SLogic capture benchmark harness

Phase 0 tool of `build/docs/slogic-driver-plan.md`: one measurement core,
interchangeable transports, one JSON document per run.

```sh
# smoke cell (32ch @ 200 MHz, Emulation, 1 s), 10 repetitions
./build/bench/capture_bench.py --transport sigrok-cli \
    --sigrok-cli "artifact/dev-nightly/<ver>/linux-x86_64-musl/sigrok-cli-SLogic-linux-x86_64.AppImage" \
    smoke

# same cell against a running ALL-LOGIC host (MCP on 127.0.0.1:10110);
# pass the host's stdout log to enable backpressure detection
./build/bench/capture_bench.py --transport mcp --app-log /tmp/alllogic.log smoke

# reproducibility gate (two passes must agree within +-3%)
./build/bench/capture_bench.py --transport mcp verify

# full matrix: channels {32,16,8,4} at top rates x patterns x {1,2,4,10}s
./build/bench/capture_bench.py --transport mcp sweep --repetitions 10 --keep-going

# comparison table across everything recorded today
./build/bench/capture_bench.py report
```

Results land under `artifact/bench/<yyyymmdd>/` (untracked). Every run
records requested and captured samples, wall time, device streaming time,
wire rate, host tail, process CPU, GUI latency (MCP only) and the
backpressure flag. The process exits non-zero when any capture is short.

Transports:

- `mcp` drives the ALL-LOGIC host over MCP JSON-RPC (`configure`,
  `start_capture`, `get_status`), polling status every 20 ms; the poll
  round-trips double as the GUI-responsiveness probe.
- `sigrok-cli` runs the CLI against the libsigrok driver with
  `-O binary`, counting raw sample bytes on stdout; stderr is scanned
  for stall markers.

Adding a transport means implementing `Transport.capture(cell)` and
registering it in `TRANSPORTS`; the matrix, JSON schema, report and
reproducibility gate stay untouched.

The device must enumerate as 359F:3032/3031/0300 (runtime). A device
sitting in DFU (359F:30F1) is invisible to both drivers.

## slogic_selftest.py — cross-platform regression gate

`slogic_selftest.py` is the routine per-platform regression gate: it checks
**functional correctness and a real throughput gate** of the libsigrok capture +
decode chain, and is run on each of Linux/macOS/Windows. It needs no external
signal: it captures the on-board Emulation/USB-test patterns to the null device
and reads the driver's `-l 4` **measured** average rate, requiring ≥ 90 % of the
expected per-mode rate — a complete capture alone is NOT full speed, since the
driver can drain at the host's slower pace. Decode regression uses golden `.sr`
fixtures. `capture_bench.py` is the optional deep throughput / baseline
characterization tool (full matrix, wall-time, ±3 % reproducibility).

```sh
# plug in a SLogic32U3, then on each platform (Windows: py -3):
python3 build/bench/slogic_selftest.py \
    --sigrok-cli <sigrok-cli-SLogic for this platform> \
    [--golden-dir <dir of <name>.sr + <name>.args + <name>.expected>] \
    [--usb-speed 10G|5G] [--min-rate-pct 90]
```

Checks version/driver/decoder (1.x), scan/show/usb-link (2.x), per-mode
{Emulation,Normal} measured rate + the USB-test max-speed probe + the
logic_channels→rate clamp warning (3.x), and golden-`.sr` decode (4.x). The USB
link speed (→ the 10G=800 / 5G=400 MB/s standard) is auto-detected on Linux/macOS
(override with `--usb-speed`; Windows can't detect it). Each row is tagged with
its checklist item ID and the run prints a paste-ready sign-off record. Exits
non-zero on any failure (or no device, unless `--allow-no-device`). See
`build/docs/regression-checklist-slogic32u3.md`.
