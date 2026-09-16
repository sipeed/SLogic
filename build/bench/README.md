# SLogic capture benchmark harness

Phase 0 tool of `build/docs/slogic-driver-plan.md`: one measurement core,
interchangeable transports, one JSON document per run.

```sh
# smoke cell (32ch @ 200 MHz, Emulation, 1 s), 10 repetitions
./build/bench/capture_bench.py --transport sigrok-cli \
    --sigrok-cli "artifact/dev-nightly/<ver>/linux-x86_64-musl/sigrok-cli-SLogic-linux-x86_64-musl.AppImage" \
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
