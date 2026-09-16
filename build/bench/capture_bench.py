#!/usr/bin/env python3
"""Host-agnostic capture benchmark harness for the SLogic drivers.

One measurement core drives interchangeable transports:

  mcp         ALL-LOGIC host over MCP JSON-RPC (generalized from
              sources/all-logic/tools/test_acceptance.py)
  sigrok-cli  sigrok-cli subprocess against the libsigrok driver

Further transports (PulseView, SLogicView) implement the same Transport
interface without touching the measurement logic.

Each run writes one JSON document under artifact/bench/<session>/.
`report` renders the cross-transport comparison table from those files.
The process exits non-zero whenever any capture comes back short.

Phase 0 of build/docs/slogic-driver-plan.md: measure, do not change
driver behaviour.
"""

import argparse
import dataclasses
import glob
import json
import os
import platform
import re
import resource
import shlex
import socket
import statistics
import subprocess
import sys
import time
import urllib.request

WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SCHEMA = "slogic-capture-bench/1"

# Channel mode -> top samplerate; every top rate saturates the same link.
TOP_RATE_HZ = {32: 200_000_000, 16: 400_000_000, 8: 800_000_000, 4: 1_600_000_000}
PATTERNS = ("Normal", "USB connection test", "Emulation")
DURATIONS_S = (1, 2, 4, 10)
SMOKE = {"channels": 32, "pattern": "Emulation", "duration_s": 1}

# ALL-LOGIC SR_CONF_CHANNEL_MODE is an index into the model's mode table;
# for SLogic32U3 the order is 32, 16, 8, 4.
MCP_CHANNEL_MODE_INDEX = {32: 0, 16: 1, 8: 2, 4: 3}

# The libsigrok driver streams sample-major bytes; below 8 channels it
# expands each sample to one byte.
def unitsize(channels):
    return max(1, channels // 8)


@dataclasses.dataclass
class Cell:
    channels: int
    samplerate_hz: int
    pattern: str
    duration_s: int

    @property
    def requested_samples(self):
        return self.samplerate_hz * self.duration_s

    def label(self):
        rate = self.samplerate_hz // 1_000_000
        return f"{self.channels}ch@{rate}MHz/{self.pattern}/{self.duration_s}s"


@dataclasses.dataclass
class RunResult:
    requested_samples: int
    captured_samples: int
    wall_s: float
    stream_s: float          # time the device was actually delivering data
    host_tail_s: float       # stream end -> transport idle
    process_cpu_s: float
    wire_rate_mbps: float    # captured bytes / stream_s
    backpressure: bool | None
    gui_latency_ms: dict | None
    notes: list


class Transport:
    """One capture backend. Implementations must not share state between
    runs beyond an already-configured device."""

    name = "abstract"

    def version(self):
        raise NotImplementedError

    def capture(self, cell: Cell) -> RunResult:
        raise NotImplementedError


class McpTransport(Transport):
    """Drives the ALL-LOGIC host over its MCP JSON-RPC endpoint."""

    name = "all-logic-mcp"

    def __init__(self, url="http://127.0.0.1:10110/mcp", app_log=None):
        self.url = url
        self.app_log = app_log
        self._id = 0
        self._pid = None

    def _call(self, tool, args=None, timeout=180, retries=20, backoff=0.25):
        self._id += 1
        body = json.dumps({
            "jsonrpc": "2.0", "id": self._id, "method": "tools/call",
            "params": {"name": tool, "arguments": args or {}},
        }).encode()
        last = "no attempt"
        for _ in range(retries):
            t0 = time.monotonic()
            try:
                req = urllib.request.Request(
                    self.url, data=body,
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                if raw:
                    text = json.loads(raw)["result"]["content"][0]["text"]
                    try:
                        return json.loads(text), time.monotonic() - t0
                    except ValueError:
                        return text, time.monotonic() - t0
                last = "empty body"
            except Exception as exc:
                last = f"{type(exc).__name__}: {exc}"
            time.sleep(backoff)
        raise RuntimeError(f"MCP call {tool} failed {retries} times (last: {last})")

    def version(self):
        try:
            state, _ = self._call("get_status")
            if isinstance(state, dict) and state.get("version"):
                return str(state["version"])
        except Exception:
            pass
        try:
            return "AllLogic pid " + str(self._pid_of_host())
        except Exception:
            return "AllLogic (version unavailable over MCP)"

    def _pid_of_host(self):
        # An AppImage runs the GUI through the bundled musl loader, so the
        # process comm is the loader name; match the command line instead.
        if self._pid is None:
            for pattern in (["-x", "AllLogic"], ["-f", "bin/AllLogic"]):
                try:
                    out = subprocess.check_output(["pgrep", *pattern], text=True)
                    self._pid = int(out.split()[0])
                    break
                except subprocess.CalledProcessError:
                    continue
            if self._pid is None:
                raise RuntimeError("no running ALL-LOGIC host process found")
        return self._pid

    def _cpu_ticks(self):
        total = 0
        for task in glob.glob(f"/proc/{self._pid_of_host()}/task/*/stat"):
            try:
                with open(task) as handle:
                    fields = handle.read().rsplit(")", 1)[1].split()
            except OSError:
                continue
            total += int(fields[11]) + int(fields[12])
        return total

    def _log_offset(self):
        if not self.app_log:
            return None
        try:
            return os.path.getsize(self.app_log)
        except OSError:
            return None

    def _log_since(self, offset):
        if self.app_log is None or offset is None:
            return None
        try:
            with open(self.app_log, "rb") as handle:
                handle.seek(offset)
                return handle.read()
        except OSError:
            return None

    STREAM_DONE = re.compile(
        rb"stream done: ([0-9.]+) MB in ([0-9.]+) s \((\d+) MB/s\), "
        rb"[0-9.]+ MSa, host tail (\d+) ms")

    def _driver_report(self, chunk):
        """The driver's own per-capture line is the device-side truth for
        stream time and host tail; keep it alongside our host-side view."""
        if chunk is None:
            return None
        matches = self.STREAM_DONE.findall(chunk)
        if not matches:
            return None
        mb, secs, rate, tail_ms = matches[-1]
        return {"stream_mb": float(mb), "stream_s": float(secs),
                "stream_mbps": int(rate), "host_tail_ms": int(tail_ms)}

    def capture(self, cell: Cell) -> RunResult:
        notes = []
        self._call("configure", {
            "pattern": cell.pattern,
            "channel_mode": MCP_CHANNEL_MODE_INDEX[cell.channels],
            "samplerate": f"{cell.samplerate_hz // 1_000_000}MHz",
            "sample_count": cell.requested_samples,
        })
        log_at = self._log_offset()
        cpu0 = self._cpu_ticks()
        t0 = time.monotonic()
        self._call("start_capture")

        latencies = []
        t_first_data = t_target = t_idle = None
        captured = 0
        deadline = t0 + cell.duration_s * 6 + 60
        while True:
            state, dt = self._call("get_status")
            now = time.monotonic()
            latencies.append(dt)
            if isinstance(state, dict):
                captured = int(state.get("captured_samples") or captured)
                if captured > 0 and t_first_data is None:
                    t_first_data = now
                if captured >= cell.requested_samples and t_target is None:
                    t_target = now
                if not state.get("capturing"):
                    t_idle = now
                    break
            if now > deadline:
                notes.append("timeout waiting for capture to finish")
                break
            time.sleep(0.02)

        wall = (t_idle or time.monotonic()) - t0
        cpu = (self._cpu_ticks() - cpu0) / os.sysconf("SC_CLK_TCK")
        stream_end = t_target or t_idle or time.monotonic()
        stream = max(stream_end - (t_first_data or t0), 1e-9)
        tail = max(((t_idle or stream_end) - stream_end), 0.0)
        latencies.sort()
        gui = {
            "avg_ms": 1000 * sum(latencies) / len(latencies),
            "p95_ms": 1000 * latencies[int(len(latencies) * 0.95)],
            "max_ms": 1000 * latencies[-1],
        } if latencies else None
        captured_bytes = captured * unitsize(cell.channels)
        chunk = self._log_since(log_at)
        driver = self._driver_report(chunk)
        if driver:
            notes.append(f"driver: {driver['stream_mb']:.0f} MB in "
                         f"{driver['stream_s']:.3f} s ({driver['stream_mbps']} MB/s), "
                         f"host tail {driver['host_tail_ms']} ms")
            stream = driver["stream_s"]
            tail = driver["host_tail_ms"] / 1000.0
        backpressure = (None if chunk is None
                        else b"USB link slower than the analyzer" in chunk)
        return RunResult(
            requested_samples=cell.requested_samples,
            captured_samples=captured,
            wall_s=wall,
            stream_s=stream,
            host_tail_s=tail,
            process_cpu_s=cpu,
            wire_rate_mbps=captured_bytes / stream / 1e6,
            backpressure=backpressure,
            gui_latency_ms=gui,
            notes=notes,
        )


class SigrokCliTransport(Transport):
    """Runs sigrok-cli as a subprocess against the libsigrok driver and
    counts raw sample bytes streamed through `-O binary`."""

    name = "sigrok-cli"
    DRIVER = "sipeed-slogic-analyzer"
    STALL_MARKERS = (b"timed out", b"timeout", b"stall", b"Device stopped")

    def __init__(self, binary="sigrok-cli", loglevel=2):
        self.binary = binary
        self.loglevel = loglevel

    def version(self):
        out = subprocess.check_output(
            shlex.split(self.binary) + ["--version"], text=True,
            stderr=subprocess.STDOUT)
        return out.splitlines()[0]

    def capture(self, cell: Cell) -> RunResult:
        notes = []
        config = (f"samplerate={cell.samplerate_hz}"
                  f":logic_channels={cell.channels}"
                  f":pattern={cell.pattern}")
        cmd = shlex.split(self.binary) + [
            "-d", self.DRIVER,
            "-c", config,
            "--samples", str(cell.requested_samples),
            "-O", "binary",
            "-l", str(self.loglevel),
        ]
        usage0 = resource.getrusage(resource.RUSAGE_CHILDREN)
        t0 = time.monotonic()
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0)
        total = 0
        t_first = t_last = None
        buf = bytearray(8 * 1024 * 1024)
        view = memoryview(buf)
        while True:
            n = proc.stdout.readinto(view)
            if not n:
                break
            now = time.monotonic()
            if t_first is None:
                t_first = now
            t_last = now
            total += n
        stderr = proc.stderr.read()
        proc.wait()
        t_exit = time.monotonic()
        usage1 = resource.getrusage(resource.RUSAGE_CHILDREN)

        if proc.returncode != 0:
            notes.append(f"sigrok-cli exit {proc.returncode}")
        for marker in self.STALL_MARKERS:
            if marker in stderr:
                notes.append("stderr: " + marker.decode())
                break
        wall = t_exit - t0
        stream = max((t_last or t_exit) - (t_first or t0), 1e-9)
        cpu = ((usage1.ru_utime + usage1.ru_stime)
               - (usage0.ru_utime + usage0.ru_stime))
        return RunResult(
            requested_samples=cell.requested_samples,
            captured_samples=total // unitsize(cell.channels),
            wall_s=wall,
            stream_s=stream,
            host_tail_s=max(t_exit - (t_last or t_exit), 0.0),
            process_cpu_s=cpu,
            wire_rate_mbps=total / stream / 1e6,
            backpressure=None,
            gui_latency_ms=None,
            notes=notes,
        )


TRANSPORTS = {"mcp": McpTransport, "sigrok-cli": SigrokCliTransport}


def workspace_commit():
    try:
        return subprocess.check_output(
            ["git", "-C", WORKSPACE, "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def cells_for(channels_list, patterns, durations):
    for channels in channels_list:
        for pattern in patterns:
            for duration in durations:
                yield Cell(channels, TOP_RATE_HZ[channels], pattern, duration)


def run_cells(transport, cells, repetitions, out_dir, keep_going):
    os.makedirs(out_dir, exist_ok=True)
    meta = {
        "schema": SCHEMA,
        "transport": transport.name,
        "transport_version": transport.version(),
        "label": getattr(transport, "label", None),
        "workspace_commit": workspace_commit(),
        "host": {
            "hostname": socket.gethostname(),
            "kernel": platform.release(),
            "machine": platform.machine(),
        },
    }
    short_runs = 0
    for cell in cells:
        for rep in range(1, repetitions + 1):
            tag = re.sub(r"[^A-Za-z0-9]+", "-", cell.label()).strip("-")
            print(f"[{transport.name}] {cell.label()} rep {rep}/{repetitions} ...",
                  end=" ", flush=True)
            result = transport.capture(cell)
            full = result.captured_samples >= result.requested_samples
            short_runs += 0 if full else 1
            record = {
                **meta,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "cell": dataclasses.asdict(cell),
                "repetition": rep,
                **dataclasses.asdict(result),
                "full": full,
            }
            path = os.path.join(out_dir, f"{transport.name}-{tag}-r{rep:02d}.json")
            with open(path, "w") as handle:
                json.dump(record, handle, indent=1)
            print(f"samples={result.captured_samples}/{result.requested_samples} "
                  f"wall={result.wall_s:.3f}s wire={result.wire_rate_mbps:.0f}MB/s"
                  + ("" if full else "  SHORT"))
            if not full and not keep_going:
                print("Short capture: stopping (use --keep-going to record and continue).")
                return short_runs
    return short_runs


def load_runs(paths):
    runs = []
    for path in paths:
        with open(path) as handle:
            doc = json.load(handle)
        if doc.get("schema") == SCHEMA:
            runs.append(doc)
    return runs


def render_table(runs):
    def key(doc):
        c = doc["cell"]
        return (c["channels"], c["pattern"], c["duration_s"], doc["transport"])

    groups = {}
    for doc in runs:
        groups.setdefault(key(doc), []).append(doc)

    lines = [
        "| Cell | Transport | Runs | Full | Wall s (mean±sd) | Wire MB/s | Tail ms | CPU s | GUI p95 ms | Backpressure |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for k in sorted(groups):
        docs = groups[k]
        c = docs[0]["cell"]
        # Timing statistics come from full captures only; a run that
        # aborts after a fraction of a transfer has no meaningful rate.
        good = [d for d in docs if d["full"]] or docs
        walls = [d["wall_s"] for d in good]
        wires = [d["wire_rate_mbps"] for d in good]
        tails = [d["host_tail_s"] * 1000 for d in good]
        cpus = [d["process_cpu_s"] for d in good]
        full = sum(1 for d in docs if d["full"])
        gui = [d["gui_latency_ms"]["p95_ms"] for d in good if d.get("gui_latency_ms")]
        bp = [d["backpressure"] for d in docs if d["backpressure"] is not None]
        sd = statistics.stdev(walls) if len(walls) > 1 else 0.0
        rate = c["samplerate_hz"] // 1_000_000
        columns = [
            f"{c['channels']}ch@{rate}MHz {c['pattern']} {c['duration_s']}s",
            docs[0]["transport"],
            str(len(docs)),
            f"{full}/{len(docs)}",
            f"{statistics.mean(walls):.3f}±{sd:.3f}",
            f"{statistics.mean(wires):.0f}",
            f"{statistics.mean(tails):.0f}",
            f"{statistics.mean(cpus):.2f}",
            f"{statistics.mean(gui):.1f}" if gui else "-",
            f"{sum(bp)}/{len(bp)}" if bp else "-",
        ]
        lines.append("| " + " | ".join(columns) + " |")
    return "\n".join(lines)


def make_transport(args):
    if args.transport == "mcp":
        transport = McpTransport(url=args.mcp_url, app_log=args.app_log)
    else:
        transport = SigrokCliTransport(binary=args.sigrok_cli,
                                       loglevel=args.loglevel)
    transport.label = args.label
    return transport


def cmd_smoke(args):
    transport = make_transport(args)
    cell = Cell(SMOKE["channels"], TOP_RATE_HZ[SMOKE["channels"]],
                SMOKE["pattern"], SMOKE["duration_s"])
    short = run_cells(transport, [cell], args.repetitions, args.out, args.keep_going)
    return 1 if short else 0


def cmd_sweep(args):
    # The smoke gate protects against misconfiguration, not against the
    # known intermittent short captures: three attempts, and one full
    # capture proves the configuration path works.
    transport = make_transport(args)
    cell = Cell(SMOKE["channels"], TOP_RATE_HZ[SMOKE["channels"]],
                SMOKE["pattern"], SMOKE["duration_s"])
    gate_attempts = 3
    short = run_cells(transport, [cell], gate_attempts, args.out, True)
    if short >= gate_attempts:
        print("Smoke cell never completed a full capture; "
              "not starting the full sweep.")
        return 1
    cells = list(cells_for(args.channels, args.patterns, args.durations))
    short += run_cells(transport, cells, args.repetitions, args.out,
                       args.keep_going)
    return 1 if short else 0


def cmd_verify(args):
    """Reproducibility gate: two passes over the smoke cell must agree
    on mean wall time and wire rate within the tolerance."""
    transport = make_transport(args)
    cell = Cell(SMOKE["channels"], TOP_RATE_HZ[SMOKE["channels"]],
                SMOKE["pattern"], SMOKE["duration_s"])
    means = []
    for _ in range(2):
        walls, wires = [], []
        for _ in range(args.repetitions):
            result = transport.capture(cell)
            if result.captured_samples < result.requested_samples:
                print("verify: short capture")
                return 1
            walls.append(result.wall_s)
            wires.append(result.wire_rate_mbps)
        means.append((statistics.mean(walls), statistics.mean(wires)))
    (w1, r1), (w2, r2) = means
    dev_wall = abs(w1 - w2) / w1 * 100
    dev_wire = abs(r1 - r2) / r1 * 100
    print(f"verify: wall {w1:.3f}s vs {w2:.3f}s ({dev_wall:.1f}%), "
          f"wire {r1:.0f} vs {r2:.0f} MB/s ({dev_wire:.1f}%), "
          f"tolerance {args.tolerance:.1f}%")
    return 0 if dev_wall <= args.tolerance and dev_wire <= args.tolerance else 1


def cmd_report(args):
    runs = load_runs(sorted(glob.glob(os.path.join(args.out, "*.json"))))
    if not runs:
        print("no runs found in", args.out)
        return 1
    print(render_table(runs))
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--transport", choices=sorted(TRANSPORTS), default="mcp")
    parser.add_argument("--out", default=os.path.join(
        WORKSPACE, "artifact", "bench",
        time.strftime("%Y%m%d")), help="directory for per-run JSON")
    parser.add_argument("--mcp-url", default="http://127.0.0.1:10110/mcp")
    parser.add_argument("--app-log", default=None,
                        help="ALL-LOGIC stdout log file, enables backpressure detection")
    parser.add_argument("--sigrok-cli", default="sigrok-cli",
                        help="sigrok-cli command (may include arguments)")
    parser.add_argument("--loglevel", type=int, default=2)
    parser.add_argument("--label", default=None,
                        help="free-form tag recorded in every run document"
                             " (e.g. the artifact build type)")
    parser.add_argument("--repetitions", type=int, default=10)
    parser.add_argument("--keep-going", action="store_true",
                        help="record short captures and continue; still exit non-zero")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("smoke", help="run the smoke cell (32ch@200MHz, Emulation, 1s)")
    sweep = sub.add_parser("sweep", help="smoke cell first, then the full matrix")
    sweep.add_argument("--channels", type=int, nargs="+", default=[32, 16, 8, 4])
    sweep.add_argument("--patterns", nargs="+", default=list(PATTERNS))
    sweep.add_argument("--durations", type=int, nargs="+", default=list(DURATIONS_S))
    verify = sub.add_parser("verify", help="check +-3% reproducibility on the smoke cell")
    verify.add_argument("--tolerance", type=float, default=3.0)
    sub.add_parser("report", help="render the comparison table from recorded runs")

    args = parser.parse_args()
    command = {"smoke": cmd_smoke, "sweep": cmd_sweep,
               "verify": cmd_verify, "report": cmd_report}[args.command]
    return command(args)


if __name__ == "__main__":
    sys.exit(main())
