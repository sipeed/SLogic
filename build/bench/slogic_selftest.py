#!/usr/bin/env python3
"""SLogic16U3/32U3 cross-platform self-test over sigrok-cli.

Runs the automatable functional AND performance regression items from
`build/docs/regression-checklist-slogic32u3.md` through a SLogic-capable
sigrok-cli, so ONE script validates the libsigrok capture + decode chain (shared
by SLogicView / PulseView / sigrok-cli) on Linux, macOS and Windows. Run the same
file on each platform — that is how the 3-platform regression is covered without
walking a GUI by hand.

No external signal source is needed:
  * the speed gate captures the device's on-board **Emulation** pattern at each
    channel mode's MAX rate and checks the driver's *measured* sustained rate
    (from -l 4) against the expected rate. A complete capture alone is NOT full
    speed: the driver can "drain at the host's pace", delivering every sample
    below real time, so throughput must be measured, not inferred. The driver's
    avg clock starts at the first byte, so a cold-start/power-down wake-up does
    not drag the figure — even the first capture after an idle reads true rate;
  * decode regression uses golden `.sr` files (optional, via --golden-dir).

Deep throughput characterization (wall-time / baseline matrix) stays in
capture_bench.py; this script is the routine per-release, per-platform gate.

Every result row is tagged with its checklist item ID (see §3 of
build/docs/regression-checklist-slogic32u3.md), and the run ends with a one-line
record — date / platform / serial / version / link — to paste straight into that
file's §5 sign-off table. So one run both executes and archives the regression.

Usage:
    python3 build/bench/slogic_selftest.py --sigrok-cli <sigrok-cli-SLogic>
    (Windows: py -3 build\\bench\\slogic_selftest.py --sigrok-cli <...\\sigrok-cli.exe>)

--sigrok-cli accepts a native executable, a Windows portable directory
(containing bin/sigrok-cli.exe), or a mounted macOS .app. The device model
(SLogic16U3 or 32U3) is auto-detected from the scan and sets the rate table.
Plug one into the machine first. Exits non-zero if any check FAILS (or the device is missing,
unless --allow-no-device).
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DRIVER_NAME = "sipeed-slogic-analyzer"
DRIVER = DRIVER_NAME             # "-d" argument; --conn appends ":conn=..."
VENDOR_ID = "359f"
# Per-model channel-mode -> max sample rate (MHz) and aggregate standard (MB/s) at the model's
# native USB link (aggregate = channels * MHz / 8; source slogic/slogic*.c). 32U3 is USB 10G
# (~800 MB/s; 4ch@1400 = 700), 16U3 is USB 5G (~400 MB/s). A 10G-native model negotiated down to a
# 5G link is capped by the 5G aggregate (half the standard): each mode runs at
# min(native max, aggregate*8/ch) — e.g. 32U3 on 5G: 4ch@800 8ch@400 16ch@200 32ch@100.
# "clamp" is an over-limit config (rate above the channel mode's max) the driver must clamp + warn about.
MODELS = {
    "SLogic32U3": {"modes": [(4, 1400), (8, 800), (16, 400), (32, 200)], "std": 800,
                   "native": "10G", "clamp": "logic_channels=32:samplerate=1400m"},
    "SLogic16U3": {"modes": [(4, 800), (8, 400), (16, 200)], "std": 400,
                   "native": "5G", "clamp": "logic_channels=16:samplerate=400m"},
}
DEFAULT_MODEL = "SLogic32U3"
DURATION_MS = 500           # per-mode capture; long enough for the sustained-rate average to settle
MIN_RATE_PCT = 90           # measured avg must reach this % of the expected per-mode rate
STRESS_ITERS = 20           # open/capture/close cycles for the leak/crash stress gate
CLAMP_RE = re.compile(r"wrap to|limit|not supported", re.IGNORECASE)
# Standard capture report (libslogic core, every host, log level info), e.g.:
#   slogic-report v1 model=SLogic32U3 ch=32 rate_mhz=200 end=ok samples=100000000/100000000
#   bytes=400000000 mbps=799.4 exp_mbps=800.0 fit_n=146 span_ms=497.3 cold_ms=7.6 ...
# mbps is the least-squares slope of cumulative bytes over transfer completion times, so it does
# not depend on transfer size and excludes the device's cold start (reported separately).
REPORT_RE = re.compile(r"slogic-report v1 (.*)$", re.M)
# Legacy (<= 2.2.0) driver -l 4 line, kept so older builds can still be measured.
SPEED_RE = re.compile(r"speed:\s*[\d.]+MBps,\s*([\d.]+)MBps\(avg\),\s*([\d.]+)MBps\(exp\)")
GOT_RE = re.compile(r"Got\s+(\d+)/\d+\(([\d.]+)%\)")
# Firmware issue F1 (duplicate block 0 at the head) is known in these (channels, MHz) modes;
# reported as KNOWN-FW, not FAIL, until the firmware fix lands (then the check is strict).
KNOWN_FW_F1 = {(8, 800), (4, 200), (4, 800), (4, 1400)}


def parse_report(err: str):
    """Last slogic-report line as a dict, or None."""
    found = REPORT_RE.findall(err)
    if not found:
        return None
    return dict(t.split("=", 1) for t in found[-1].split() if "=" in t)


def _bps_to_gen(bps: int) -> str:
    if bps >= 10_000_000_000:
        return "10G"
    if bps >= 5_000_000_000:
        return "5G"
    return "unknown"


def probe_usb_speed(cli: "Path", env: dict, spec: dict) -> str:
    """Empirically classify the USB link where the OS can't report it (Windows): run a short
    raw-link USB-test capture and compare the measured rate to the model's native aggregate.
    A full 10G link clears ~70% of the 10G standard on this test; a 5G link tops out near half.
    Only meaningful for a 10G-native model (is it full 10G or degraded to 5G?)."""
    nch, mhz = spec["modes"][-1]
    samples = int(mhz * 1_000_000 * 150 / 1000)   # ~150 ms probe
    cfg = f"logic_channels={nch}:samplerate={mhz}m:pattern=USB connection test"
    try:
        rc, _, err = run(cli, env, ["-d", DRIVER, "-l", "4", "--config", cfg,
                                    "--samples", str(samples), "-O", "binary", "-o", os.devnull],
                         timeout=60)
    except Exception:
        return "unknown"
    kv, speeds = parse_report(err), SPEED_RE.findall(err)
    if rc != 0 or not (kv or speeds):
        return "unknown"
    try:
        mbps = float(kv["mbps"]) if kv else float(speeds[-1][0])
    except ValueError:
        return "unknown"
    return "10G" if mbps >= 0.70 * spec["std"] else "5G"


def detect_usb_speed() -> str:
    """Best-effort USB link speed of the SLogic device: '10G', '5G', or 'unknown'."""
    try:
        if os.name == "nt":
            return "unknown"  # TODO: PnP/WMI query on Windows
        if sys.platform == "darwin":
            # ioreg exposes the negotiated link speed in bit/s as "UsbLinkSpeed"
            # (system_profiler SPUSBDataType is empty on some macOS builds).
            out = subprocess.run(["ioreg", "-rc", "IOUSBHostDevice"],
                                 capture_output=True, text=True, timeout=25).stdout
            for block in out.split("+-o "):
                if "slogic" in block.lower() or "sipeed" in block.lower():
                    m = re.search(r'"UsbLinkSpeed"\s*=\s*(\d+)', block)
                    if m:
                        return _bps_to_gen(int(m.group(1)))
            return "unknown"
        # linux: read the negotiated speed (Mbit/s) from sysfs for the 359f device
        for vid_file in glob.glob("/sys/bus/usb/devices/*/idVendor"):
            try:
                if Path(vid_file).read_text().strip().lower() != VENDOR_ID:
                    continue
                sp = (Path(vid_file).parent / "speed").read_text().strip()
                return {"5000": "5G", "10000": "10G"}.get(sp, "unknown")
            except OSError:
                continue
    except Exception:
        pass
    return "unknown"


# ---------------------------------------------------------------- cli resolution
def _sha256(path: Path) -> str:
    """Streamed sha256 of the resolved sigrok-cli binary (records exactly what was tested)."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return "?"
    return h.hexdigest()


def resolve_cli(explicit: str) -> Path:
    win = os.name == "nt"
    mac = sys.platform == "darwin"
    p = Path(explicit).expanduser()
    if p.suffix.lower() == ".dmg":
        sys.exit("a .dmg is a disk image; mount it and pass the .app or Contents/MacOS/sigrok-cli")
    candidates: list[Path] = []
    if p.is_dir():
        if mac and p.suffix.lower() == ".app":
            candidates.append(p / "Contents/MacOS/sigrok-cli")
        for name in (("sigrok-cli.exe", "sigrok-cli") if win else ("sigrok-cli",)):
            candidates += [p / name, p / "bin" / name, p / "sr/bin" / name]
    else:
        candidates.append(p)
    for c in candidates:
        c = c.resolve()
        if c.is_file() and (win or os.access(c, os.X_OK)):
            return c
    sys.exit(f"sigrok-cli not found or not executable at: {explicit}")


def cli_env(cli: Path) -> dict[str, str]:
    env = os.environ.copy()
    adjacent = [cli.parent, cli.parent / "lib", cli.parent.parent / "lib"]
    if os.name == "nt":
        key, extra = "PATH", adjacent
    elif sys.platform == "darwin":
        key, extra = "DYLD_LIBRARY_PATH", [cli.parent.parent / "Frameworks", *adjacent[1:]]
    else:
        key, extra = "LD_LIBRARY_PATH", adjacent[1:]
    values = [str(d) for d in extra if d.is_dir()]
    if env.get(key):
        values.append(env[key])
    if values:
        env[key] = os.pathsep.join(values)
    return env


def run(cli: Path, env: dict, args: list[str], *, binary: bool = False, timeout: int = 180):
    cp = subprocess.run([str(cli), *args], env=env, capture_output=True, timeout=timeout)
    out = cp.stdout if binary else cp.stdout.decode("utf-8", "replace")
    err = cp.stderr.decode("utf-8", "replace")
    return cp.returncode, out, err


# ---------------------------------------------------------------------- results
class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str, float]] = []

    def add(self, cid: str, name: str, status: str, detail: str, ms: float) -> None:
        self.rows.append((cid, name, status, detail, ms))
        print(f"  [{status:4}] {cid:4} {name:27}{int(ms):5d}ms  {detail}")

    def counts(self) -> tuple[int, int, int, int]:
        st = [r[2] for r in self.rows]
        return st.count("PASS"), st.count("FAIL"), st.count("SKIP"), st.count("KFW")


def timed(fn):
    """fn returns (ok, detail); ok may also be a status string such as "KFW"."""
    t0 = time.monotonic()
    ok, detail = fn()
    status = ok if isinstance(ok, str) else ("PASS" if ok else "FAIL")
    return status, detail, (time.monotonic() - t0) * 1000


# ------------------------------------------------------------------------ checks
_BIT_PLANES = [bytes(((b >> k) & 1) for b in range(256)) for k in range(8)]
_INVERT = bytes([1, 0]) + bytes(254)


def check_periods(out: bytes, nch: int, u: int):
    """Emulation integrity: every channel is a square wave with a fixed half-period h;
    require x[i+h] == !x[i] for every sample. Returns (ok, detail, half_periods)."""
    halves, bad = [], []
    for ch in range(nch):
        col = out[ch // 8::u] if u > 1 else out
        plane = col.translate(_BIT_PLANES[ch % 8])
        first = plane[0:1]
        t1 = plane.find(b"\x01" if first == b"\x00" else b"\x00")
        t2 = plane.find(first, t1) if t1 >= 0 else -1
        if t1 < 0 or t2 < 0:
            bad.append(f"CH{ch}: fewer than two edges")
            continue
        h = t2 - t1
        if 4 * h > len(plane):
            halves.append(f"{h}(skipped)")
            continue
        a, b = plane[h:], plane[:-h].translate(_INVERT)
        if a != b:
            lo, hi = 0, len(a)              # first differing sample, by bisection
            while hi - lo > 1:
                mid = (lo + hi) // 2
                lo, hi = (mid, hi) if a[:mid] == b[:mid] else (lo, mid)
            bad.append(f"CH{ch}: half-period {h} broken at sample {lo + h}")
            continue
        halves.append(str(h))
    if bad:
        return False, "; ".join(bad[:4]) + (f" (+{len(bad) - 4} more)" if len(bad) > 4 else ""), halves
    return True, "", halves


def load_emulation_spec(path: Path, model: str, nch: int):
    """Expected Emulation pattern for (model, nch) from emulation.json, or None.
    Returns {"bits", "start", "channels": [(bit or None, invert or const)]}."""
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    m = spec.get("models", {}).get(model)
    chans = (m or {}).get("channels", {}).get(str(nch))
    if not chans:
        return None
    rules = []
    for expr in chans:
        expr = str(expr).strip()
        if expr in ("0", "1"):
            rules.append((None, int(expr)))
        else:
            mm = re.fullmatch(r"(~?)c(\d+)", expr)
            if not mm:
                raise ValueError(f"emulation spec: bad channel rule {expr!r}")
            rules.append((int(mm.group(2)), 1 if mm.group(1) else 0))
    if len(rules) != nch:
        raise ValueError(f"emulation spec: {model} {nch}ch lists {len(rules)} channels")
    counter = m.get("counter", {})
    return {"bits": int(counter.get("bits", 16)), "start": counter.get("start"), "channels": rules}


_SPEC_PERIODS = {}


def _spec_period(spec: dict, u: int):
    """One full period of the expected sample stream, starting at counter 0."""
    rules = spec["channels"]
    key = (tuple(rules), spec["bits"], u)
    if key not in _SPEC_PERIODS:
        top = max([b for b, _ in rules if b is not None] or [0])
        period = 1 << min(top + 1, spec["bits"])
        words = []
        for c in range(period):
            w = 0
            for ch, (bit, inv) in enumerate(rules):
                v = inv if bit is None else ((c >> bit) & 1) ^ inv
                w |= v << ch
            words.append(w.to_bytes(u, "little"))
        _SPEC_PERIODS[key] = (period, b"".join(words))
    return _SPEC_PERIODS[key]


def _spec_slip(out: bytes, s: int, u: int, base: bytes, period: int, start: int, reach: int = 64,
               run: int = 16):
    """At the first wrong sample s: if the stream resumes the expected pattern shifted by d samples
    (d > 0: d samples missing, d < 0: repeated), return d, else 0. Needs `run` matching samples."""
    got = out[s * u:(s + run) * u]
    if len(got) < run * u:
        return 0

    def expected(j):
        k = (start + j) % period
        seq = base[k * u:] + base[:k * u]
        while len(seq) < run * u:
            seq += base
        return seq[:run * u]
    for d in sorted(range(-reach, reach + 1), key=abs):
        if d and s + d >= 0 and expected(s + d) == got:
            return d
    return 0


def check_spec(out: bytes, nch: int, u: int, spec: dict):
    """Compare every sample with the Emulation spec (frequency, duty cycle and phase of
    every channel, and the counter start). Returns (ok, detail)."""
    period, base = _spec_period(spec, u)
    n = len(out) // u
    first = out[:u]
    if spec["start"] is not None:
        start = int(spec["start"]) % period
    else:                                   # free-running: phase from the first sample
        start = next((c for c in range(period) if base[c * u:(c + 1) * u] == first), None)
        if start is None:
            return False, f"sample 0 (0x{int.from_bytes(first, 'little'):0{2 * u}x}) is not in the pattern"
    ring = base[start * u:] + base[:start * u]
    ring *= max(1, (1 << 20) // len(ring))  # compare ~1 MiB at a time (whole periods)
    plen = len(ring)
    for off in range(0, n * u, plen):
        chunk = out[off:off + plen]
        if chunk != ring[:len(chunk)]:
            i = next(k for k in range(0, len(chunk), u) if chunk[k:k + u] != ring[k:k + u])
            got = int.from_bytes(chunk[i:i + u], "little")
            want = int.from_bytes(ring[i:i + u], "little")
            s = (off + i) // u
            slip = _spec_slip(out, s, u, base, period, start)
            if slip:
                return False, (f"sample {s} (byte 0x{s * u:x}): {abs(slip)} sample(s) "
                               f"{'missing' if slip > 0 else 'repeated'} ({abs(slip) * u} bytes), "
                               f"the stream continues {abs(slip)} sample(s) {'ahead' if slip > 0 else 'behind'}")
            diff = [f"CH{ch}" for ch in range(nch) if (got ^ want) >> ch & 1]
            return False, (f"sample {s}: {', '.join(diff[:8])}{' ...' if len(diff) > 8 else ''} "
                           f"wrong (got 0x{got:0{2 * u}x}, want 0x{want:0{2 * u}x})")
    return True, f"all {n} samples match the Emulation spec"


def emulation_check(out: bytes, nch: int, u: int, spec):
    """The 3.9 / soak check: the spec when one is defined, else the per-channel period check."""
    if spec is not None:
        return check_spec(out, nch, u, spec)
    ok, detail, halves = check_periods(out, nch, u)
    return ok, detail if not ok else ("every channel's period exact (no Emulation spec for this mode: "
                                      f"half-periods {', '.join(halves[:4])} ... {halves[-1]})")


def soak(capture_bytes, nch: int, mhz: int, u: int, std: int, args, spec=None):
    """--soak: capture -> verify -> discard in a loop, alternating Emulation and Normal."""
    n = mhz * 1000 * args.soak_ms
    exp_mbps = mhz * nch / 8
    end_at = time.monotonic() + args.soak * 60
    stats = {"Emulation": [0, 0], "Normal": [0, 0]}    # rounds, failures
    failures, rnd, t0 = [], 0, time.monotonic()
    print(f"  soak: {nch}ch@{mhz}MHz, {args.soak_ms} ms ({n} samples) per round, "
          f"{args.soak:g} min, Emulation + Normal (floating inputs); Emulation checked "
          f"{'against the spec' if spec else 'per channel period (no spec for this mode)'}")
    try:
        while time.monotonic() < end_at:
            rnd += 1
            pattern = "Emulation" if rnd % 2 else "Normal"
            rc, out, err = capture_bytes(nch, mhz, n, pattern)
            kv = parse_report(err.decode("utf-8", "replace") if isinstance(err, bytes) else err)
            problem = ""
            if rc != 0 or len(out) != n * u:
                tail = (err.decode("utf-8", "replace") if isinstance(err, bytes) else err).strip().splitlines()
                problem = f"rc={rc} got {len(out)}B want {n * u}B {tail[-1][:80] if tail else ''}"
            elif not kv or kv.get("end") != "ok":
                problem = f"end={kv.get('end') if kv else 'no report'}"
            elif pattern == "Emulation":
                ok, detail = emulation_check(out, nch, u, spec)
                problem = "" if ok else detail
            else:
                try:
                    mbps = float(kv.get("mbps", "nan"))
                except ValueError:
                    mbps = float("nan")
                if not mbps >= exp_mbps * args.min_rate_pct / 100:
                    problem = f"rate {kv.get('mbps')} MB/s < {args.min_rate_pct}% of {exp_mbps:g}"
            del out
            stats[pattern][0] += 1
            elapsed = time.monotonic() - t0
            if problem:
                stats[pattern][1] += 1
                failures.append(f"round {rnd} {pattern}: {problem}")
            print(f"  soak {rnd:5d} {int(elapsed // 60):3d}:{int(elapsed % 60):02d} {pattern:9} "
                  f"{'OK' if not problem else 'FAIL ' + problem}", flush=True)
    except KeyboardInterrupt:
        print("  soak: stopped by Ctrl+C")
    verified = stats["Emulation"][0] - stats["Emulation"][1]
    summary = (f"{rnd} rounds in {(time.monotonic() - t0) / 60:.1f} min; Emulation "
               f"{stats['Emulation'][0]} rounds ({verified * n:,} samples exact), "
               f"{stats['Emulation'][1]} failed; Normal {stats['Normal'][0]} rounds, {stats['Normal'][1]} failed")
    if failures:
        summary += " | first: " + "; ".join(failures[:3])
    return (rnd > 0 and not failures), summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sigrok-cli", required=True, help="path to sigrok-cli (executable, portable dir, or .app)")
    ap.add_argument("--golden-dir", help="directory of <name>.sr + <name>.args + <name>.expected decode fixtures")
    ap.add_argument("--duration-ms", type=int, default=None,
                    help=f"per-mode capture duration in ms (default {DURATION_MS}, 1500 on macOS whose large "
                         "USB transfers leave few points for the rate fit)")
    ap.add_argument("--min-rate-pct", type=int, default=MIN_RATE_PCT,
                    help=f"measured avg rate must reach this %% of the expected per-mode rate (default {MIN_RATE_PCT})")
    ap.add_argument("--stress-iters", type=int, default=STRESS_ITERS,
                    help=f"open/capture/close cycles for the stress gate (default {STRESS_ITERS})")
    ap.add_argument("--usb-speed", choices=("10G", "5G"),
                    help="force the USB link speed standard (default: auto-detect); 5G halves rates + the MB/s standard")
    ap.add_argument("--allow-no-device", action="store_true", help="run device-independent checks only if no device is found")
    ap.add_argument("--conn", metavar="VID.PID|BUS.ADDR",
                    help="pick one analyzer when several are connected, e.g. 359f.3031 (SLogic16U3) or 2.17 "
                         "(needs a sigrok-cli whose driver supports conn=)")
    ap.add_argument("--soak", type=float, metavar="MINUTES",
                    help="soak test only: after device detection, loop capture -> verify -> discard for this many "
                         "minutes at the widest mode's top rate, alternating Emulation (every sample of every "
                         "channel must keep its exact period, as 3.9) and Normal with floating inputs (exact "
                         "sample count, end=ok, full rate). Ctrl+C stops early with a summary")
    ap.add_argument("--soak-ms", type=int, default=250, help="capture length per soak round in ms (default 250)")
    ap.add_argument("--emulation-spec", default=str(Path(__file__).resolve().parent / "emulation.json"),
                    help="expected Emulation pattern (default: emulation.json next to this script)")
    args = ap.parse_args()
    global DRIVER
    if args.conn:
        DRIVER = f"{DRIVER_NAME}:conn={args.conn}"
    if args.duration_ms is None:
        args.duration_ms = 1500 if sys.platform == "darwin" else DURATION_MS
    if args.golden_dir is None and (Path(__file__).resolve().parent / "golden").is_dir():
        args.golden_dir = str(Path(__file__).resolve().parent / "golden")  # bundled fixtures

    cli = resolve_cli(args.sigrok_cli)
    env = cli_env(cli)
    rep = Report()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    info = {"date": started[:10], "platform": f"{sys.platform} ({os.name})", "os": sys.platform,
            "cli": str(cli), "sha256": _sha256(cli), "version": "?",
            "model": DEFAULT_MODEL, "vidpid": "?", "serial": "?", "link": "?",
            "std": MODELS[DEFAULT_MODEL]["std"],
            "settings": f"duration {args.duration_ms}ms  min-rate {args.min_rate_pct}%"}
    print(f"SLogic self-test  |  {started}")
    print(f"sigrok-cli: {cli}\nplatform:   {info['platform']}\n")

    # --- 1. functional chain (device-independent) ---
    def c_version():
        rc, out, _ = run(cli, env, ["--version"])
        info["version"] = out.splitlines()[0].replace("sigrok-cli ", "") if out else "?"
        ok = rc == 0 and "libsigrok" in out and "libsigrokdecode" in out
        head = out.splitlines()[0] if out else "no output"
        return ok, f"{head}  sha256:{info['sha256'][:16]}…"
    rep.add("1.1", "version", *timed(c_version))

    def c_driver():
        rc, out, _ = run(cli, env, ["-L"])
        return (rc == 0 and DRIVER_NAME in out), f"{DRIVER_NAME} " + ("present" if DRIVER_NAME in out else "MISSING")
    rep.add("1.2", "driver", *timed(c_driver))

    def c_decoder():
        rc, out, _ = run(cli, env, ["--protocol-decoders", "uart", "--show"])
        return (rc == 0 and "UART" in out), "uart decoder " + ("loads" if "UART" in out else "FAILED to load")
    rep.add("1.3", "decoder", *timed(c_decoder))

    # --- 2. device presence (-l 4 so the driver logs the device VID:PID) ---
    rc, scan_out, scan_err = run(cli, env, ["-d", DRIVER, "-l", "4", "--scan"])
    device_present = rc == 0 and bool(scan_out.strip()) and ("SLogic" in scan_out or "slogic" in scan_out.lower())
    mvp = re.search(r"VID:PID\s*=\s*([0-9a-fA-F]{4}:[0-9a-fA-F]{4})", scan_err)
    if mvp:
        info["vidpid"] = mvp.group(1).lower()
    msn = re.search(r"S/N:\s*([A-Za-z0-9]+)", scan_out + scan_err)
    if msn:
        info["serial"] = msn.group(1)
    mmod = re.search(r"SLogic\s*(\d+)\s*U3", scan_out)   # "Sipeed SLogic16 U3" / "SLogic32 U3"
    if mmod:
        name = f"SLogic{mmod.group(1)}U3"
        info["model"] = name if name in MODELS else info["model"]
    scan_detail = (f"{info['model']}  VID:PID {info['vidpid']}  S/N {info['serial']}" if device_present
                   else (scan_out.strip().splitlines()[0] if scan_out.strip() else "no device found"))
    rep.add("2.1", "scan", "PASS" if device_present else ("SKIP" if args.allow_no_device else "FAIL"),
            scan_detail, 0.0)

    if not device_present:
        if not args.allow_no_device:
            print("\nNo SLogic device found — connect a SLogic16U3/32U3 (or pass --allow-no-device).")
        return _finish(rep, info)

    # --- device-dependent ---
    def c_show():
        rc, out, _ = run(cli, env, ["-d", DRIVER, "--show"])
        m = re.search(r"S/N:\s*([A-Za-z0-9]+)", out)
        if m:
            info["serial"] = m.group(1)
        ok = rc == 0 and "samplerate" in out and ("logic_channels" in out or "Logic" in out)
        return ok, "lists samplerate + logic_channels" if ok else "show missing keys"
    rep.add("2.2", "show", *timed(c_show))

    # 2.3 Per-model rates + standard. A 10G-native model (32U3) on a 5G link halves both; a 5G-native
    # model (16U3) keeps its native rates. Windows can't report the link gen (shown "unknown").
    spec = MODELS.get(info["model"], MODELS[DEFAULT_MODEL])
    link = args.usb_speed or detect_usb_speed()
    src = "forced" if args.usb_speed else "auto"
    if not args.usb_speed and link == "unknown":
        # OS can't report the link gen (Windows). A 5G-native model is at its native link;
        # a 10G-native model might be degraded to 5G, so probe it empirically.
        if spec["native"] == "10G":
            probed = probe_usb_speed(cli, env, spec)
            link, src = (probed, "probe") if probed != "unknown" else (spec["native"], "assume")
        else:
            link, src = spec["native"], "native"
    if spec["native"] == "10G" and link == "5G":
        std = spec["std"] // 2
        # 5G caps the aggregate, not each rate: 4ch keeps a higher rate than a plain halving
        modes = [(ch, min(mhz, std * 8 // ch)) for ch, mhz in spec["modes"]]
        link_desc = "5G (10G link degraded)"
    else:
        modes = spec["modes"]
        std = spec["std"]
        link_desc = link if link != "unknown" else f"unknown (assume {spec['native']})"
    info["link"], info["std"] = link, std
    print(f"  [----] 2.3  usb-link                  {link_desc} ({src}) - "
          f"{info['model']} standard {std} MB/s\n")

    def unit_of(nch):
        return 1 if nch <= 8 else nch // 8

    def capture_bytes(nch, mhz, n, pattern="Emulation", extra=None):
        cfg = f"logic_channels={nch}:samplerate={mhz}m:pattern={pattern}"
        rc, out, err = run(cli, env, ["-d", DRIVER, "-l", "3", "--config", cfg, "--samples", str(n),
                                      *(extra or []), "-O", "binary"], binary=True, timeout=60)
        # <= 2.2.0 sent a frame marker, which the binary output writes as text
        if out.startswith(b"FRAME-BEGIN\n"):
            out = out[len(b"FRAME-BEGIN\n"):]
        if out.endswith(b"FRAME-END\n"):
            out = out[:-len(b"FRAME-END\n")]
        return rc, out, err

    emu_spec = load_emulation_spec(Path(args.emulation_spec), info["model"], modes[-1][0])

    if args.soak:
        nch, mhz = modes[-1]
        rep.add("5.1", f"soak-{nch}ch@{mhz}MHz",
                *timed(lambda: soak(capture_bytes, nch, mhz, unit_of(nch), std, args, emu_spec)))
        return _finish(rep, info)

    # Real throughput test. The driver can "drain at the host's pace": when the USB link is slower
    # than the analyzer it still delivers every requested sample, just below real time — so a
    # complete capture is NOT proof of full speed. Capture at each mode's MAX rate with the driver's
    # -l 4 speed log, write the stream to the null device (so the disk is not the bottleneck), then
    # parse the driver's reported sustained average rate and require it to reach the expected
    # per-mode rate. That measured rate — not mere completeness — is the speed gate.
    cap_timeout = 120 + args.duration_ms * 60 // 1000

    def measure_rate(nch, mhz, pattern):
        """Capture to the null device and read the driver's report.
        Returns (dict(mbps, exp, ok_count, mb, span_ms, cold_ms, fit_n, end), None) or (None, errmsg)."""
        samples = int(mhz * 1_000_000 * args.duration_ms / 1000)
        cfg = f"logic_channels={nch}:samplerate={mhz}m:pattern={pattern}"  # ':' separates settings
        rc, _, err = run(cli, env, ["-d", DRIVER, "-l", "4", "--config", cfg,
                                    "--samples", str(samples), "-O", "binary", "-o", os.devnull],
                         timeout=cap_timeout)
        if rc != 0:
            return None, f"rc={rc} {err.strip().splitlines()[-1] if err.strip() else ''}"
        kv = parse_report(err)
        if kv:
            got, _, lim = kv.get("samples", "0/0").partition("/")
            num = lambda k: float(kv[k]) if kv.get(k, "nan") != "nan" else 0.0
            return dict(mbps=num("mbps"), exp=num("exp_mbps"), ok_count=got == lim,
                        mb=int(kv.get("bytes", 0)) / 1e6, span_ms=num("span_ms"),
                        cold_ms=num("cold_ms"), fit_n=int(kv.get("fit_n", 0)),
                        end=kv.get("end", "?")), None
        speeds, gots = SPEED_RE.findall(err), GOT_RE.findall(err)   # legacy <= 2.2.0 driver
        if not speeds:
            return None, "driver printed no slogic-report line (need -l 3 or more)"
        cap = float(gots[-1][1]) if gots else 0.0
        return dict(mbps=float(speeds[-1][0]), exp=float(speeds[-1][1]), ok_count=cap >= 99.9,
                    mb=(int(gots[-1][0]) / 1e6) if gots else 0.0, span_ms=0.0, cold_ms=0.0,
                    fit_n=99, end="ok"), None

    # Aligned columns so rates line up for an at-a-glance compare; volume, fitted span and the
    # cold start make each figure checkable by hand.
    def fmt(r, ref):
        pct = (r["mbps"] / ref * 100.0) if ref else 0.0
        return (f"{r['mbps']:6.1f} /{ref:6.1f} MB/s  {pct:4.0f}%   {r['mb']:7.1f} MB  "
                f"{r['span_ms']:7.1f} ms  cold {r['cold_ms']:5.1f} ms  fit {r['fit_n']}"), pct

    def judge(r, ref, min_pct, slow_word):
        detail, pct = fmt(r, ref)
        if r["end"] != "ok":
            return False, f"end={r['end']} " + detail
        if not r["ok_count"]:
            return False, "incomplete " + detail
        if r["fit_n"] < 3:
            return False, "few transfers for the rate fit, raise --duration-ms; " + detail
        if pct < min_pct:
            return False, slow_word + detail
        if pct > 105:
            return False, "implausible (measurement bug?) " + detail
        return True, detail

    # Normal + Emulation at each mode's MAX rate: the sampled data rate must reach the expected rate.
    for nch, mhz in modes:
        for pat in ("Emulation", "Normal"):
            def c_rate(nch=nch, mhz=mhz, pat=pat):
                res, errmsg = measure_rate(nch, mhz, pat)
                if res is None:
                    return False, errmsg
                return judge(res, res["exp"], args.min_rate_pct, "SLOW       ")
            rep.add("3.1", f"rate-{nch}ch@{mhz}MHz-{pat}", *timed(c_rate))

    # USB connection test (the max-speed pattern): raw link throughput, must reach or exceed the standard.
    def c_maxspeed():
        nch, mhz = modes[-1]
        res, errmsg = measure_rate(nch, mhz, "USB connection test")
        if res is None:
            return False, errmsg
        ok, detail = judge(res, float(std), 100, "below std  ")
        if not ok and detail.startswith("implausible"):
            return True, detail[len("implausible (measurement bug?) "):]  # link may exceed std
        return ok, detail
    rep.add("3.2", "maxspeed-USBtest", *timed(c_maxspeed))

    def c_clamp():
        cfg = spec["clamp"] + ":pattern=Emulation"  # rate over the model's channel-mode max
        rc, _, err = run(cli, env, ["-d", DRIVER, "--config", cfg, "--samples", "1000", "-O", "binary"], binary=True)
        ok = rc == 0 and bool(CLAMP_RE.search(err))
        return ok, "over-limit rate clamped with warning" if ok else f"no clamp warning (rc={rc})"
    rep.add("3.3", "rate-clamp-warns", *timed(c_clamp))

    # 3.4 stress: many open/capture/close cycles — catches handle/memory leaks and the
    # device-busy-after-close class of bug (no signal needed, tiny Emulation captures).
    def c_stress():
        n = max(1, args.stress_iters)
        cfg = "logic_channels=8:samplerate=10m:pattern=Emulation"
        for i in range(n):
            rc, _, err = run(cli, env, ["-d", DRIVER, "--config", cfg, "--samples", "100000",
                                        "-O", "binary", "-o", os.devnull], timeout=30)
            if rc != 0:
                last = err.strip().splitlines()[-1] if err.strip() else ""
                return False, f"iter {i + 1}/{n} failed (rc={rc}) {last}"
        return True, f"{n}x open/capture/close all OK"
    rep.add("3.4", "stress", *timed(c_stress))

    # --- 3.5-3.8: the few firmware-team cases kept here (host_test.py stays with them) ---

    # 3.5 exact sample counts, incl. counts whose packed size is not word-aligned (4ch n=1002
    # used to crash, odd counts lost a sample).
    def c_counts(nch, mhz):
        bad = []
        for n in (999, 1001, 1002, 1004, 100001):
            rc, out, _ = capture_bytes(nch, mhz, n)
            if rc != 0 or len(out) != n * unit_of(nch):
                bad.append(f"n={n}: rc={rc} got {len(out)}B want {n * unit_of(nch)}B")
        return (not bad), ("999/1001/1002/1004/100001 exact" if not bad else "; ".join(bad))
    for nch, mhz in modes:
        rep.add("3.5", f"exact-count-{nch}ch@{mhz}MHz", *timed(lambda nch=nch, mhz=mhz: c_counts(nch, mhz)))

    # 3.6 Emulation head: firmware F1 emits a duplicate block 0 (8 samples) at the head in
    # some modes. Known modes -> KNOWN-FW (does not fail the run); elsewhere -> FAIL.
    def c_head(nch, mhz):
        u = unit_of(nch)
        rc, out, _ = capture_bytes(nch, mhz, 64)
        if rc != 0 or len(out) < 16 * u:
            return False, f"rc={rc} got {len(out)}B"
        dup = out[:8 * u] == out[8 * u:16 * u]
        if not dup:
            return True, "head OK (no duplicate block)" + (
                " - F1 looks fixed in this mode" if (nch, mhz) in KNOWN_FW_F1 else "")
        if (nch, mhz) in KNOWN_FW_F1:
            return "KFW", "duplicate block 0 at head (firmware F1, known)"
        return False, "duplicate block 0 at head (firmware F1) in an unexpected mode"
    for nch, mhz in modes:
        rep.add("3.6", f"emu-head-{nch}ch@{mhz}MHz", *timed(lambda nch=nch, mhz=mhz: c_head(nch, mhz)))

    # 3.7 continuous capture starts, streams and stops on request.
    def c_continuous():
        nch, mhz = modes[-1]
        cfg = f"logic_channels={nch}:samplerate={mhz}m:pattern=Emulation"
        p = subprocess.Popen([str(cli), "-d", DRIVER, "-l", "3", "--config", cfg, "--continuous",
                              "-O", "binary", "-o", os.devnull], env=env, stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        time.sleep(2.0)
        try:
            p.stdin.write(b"x\n")
            p.stdin.flush()
        except OSError:
            pass
        try:
            _, err = p.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
            return False, "did not stop within 15 s of the stop request"
        kv = parse_report(err.decode("utf-8", "replace"))
        if p.returncode != 0 or not kv:
            return False, f"rc={p.returncode}, no report (continuous not supported?)"
        got = int(kv.get("samples", "0/0").split("/")[0])
        ok = kv.get("end") == "ok" and got > 0
        return ok, f"end={kv.get('end')} streamed {got} samples, {kv.get('mbps')} MB/s"
    rep.add("3.7", "continuous", *timed(c_continuous))

    # 3.8 trigger position: 10% pre-trigger lands exactly at sample 10000 of 100000.
    def c_trigger():
        nch = 8 if any(c == 8 for c, _ in modes) else modes[0][0]
        rc, out, err = capture_bytes(nch, 10, 100000,
                                     extra=["--triggers", "D0=r", "--config", "captureratio=10"])
        kv = parse_report(err.decode("utf-8", "replace") if isinstance(err, bytes) else err)
        if rc != 0 or len(out) != 100000:
            return False, f"rc={rc} got {len(out)}B want 100000B"
        edge = (out[9999] & 1) == 0 and (out[10000] & 1) == 1
        trig = kv.get("trig") if kv else None
        ok = edge and trig == "at:10000,pre:10000"
        return ok, f"trig={trig}, D0 {out[9999] & 1}->{out[10000] & 1} at sample 10000"
    rep.add("3.8", "trigger-position", *timed(c_trigger))

    # 3.9 data integrity: in Emulation every channel is a square wave with a fixed
    # half-period (CH0 1 sample, CH1 2, CH2 4, ...). At the widest mode's top rate, capture
    # ~250 ms and require x[i+h] == !x[i] for every sample of every channel: one shifted,
    # dropped, duplicated or corrupted sample anywhere fails the check.
    def c_period():
        nch, mhz = modes[-1]
        n = mhz * 250_000                       # 250 ms
        u = unit_of(nch)
        rc, out, _ = capture_bytes(nch, mhz, n)
        if rc != 0 or len(out) != n * u:
            return False, f"rc={rc} got {len(out)}B want {n * u}B"
        ok, detail = emulation_check(out, nch, u, emu_spec)
        return ok, f"{nch}ch@{mhz}MHz: {detail}"
    rep.add("3.9", f"emu-period-{modes[-1][0]}ch@{modes[-1][1]}MHz", *timed(c_period))

    # --- decode regression against golden .sr (optional) ---
    if args.golden_dir:
        gdir = Path(args.golden_dir).expanduser()
        srs = sorted(gdir.glob("*.sr")) if gdir.is_dir() else []
        if not srs:
            rep.add("4.1", "decode-golden", "SKIP", f"no .sr fixtures in {gdir}", 0.0)
        for sr in srs:
            def c_golden(sr=sr):
                argf, expf = sr.with_suffix(".args"), sr.with_suffix(".expected")
                if not argf.is_file() or not expf.is_file():
                    return False, f"missing {argf.name}/{expf.name} sidecar"
                dec_args = argf.read_text(encoding="utf-8").split()
                rc, out, err = run(cli, env, ["-i", str(sr), *dec_args])
                expected = expf.read_text(encoding="utf-8").strip()
                ok = rc == 0 and out.strip() == expected
                return ok, "matches golden" if ok else f"differs (rc={rc})"
            rep.add("4.1", f"decode:{sr.stem}", *timed(c_golden))
    else:
        rep.add("4.1", "decode-golden", "SKIP", "no --golden-dir given", 0.0)

    return _finish(rep, info)


def _finish(rep: Report, info: dict) -> int:
    p, f, s, k = rep.counts()
    result = "FAIL" if f else "PASS"
    print(f"\n{'='*72}")
    print(f"PASS {p}   FAIL {f}   SKIP {s}   KNOWN-FW {k}   ->  RESULT: {result}")
    # Provenance + a one-line record to paste into the checklist §4 sign-off table.
    print("\n归档(build/docs/regression-checklist-slogic32u3.md §5):")
    print(f"  日期 {info['date']} | 平台 {info['os']} | 设备 {info['model']} {info['vidpid']} S/N {info['serial']} | "
          f"USB链路 {info['link']} | {info['settings']}")
    print(f"  sigrok-cli {info['version']}  sha256:{info['sha256']}")
    print("  可粘贴签收行(固件/build/操作人自填):")
    print(f"  | {info['date']} | <固件> | <build> | {info['os']} | {info['serial']} | <操作人> | {result} {p}/{f}/{s} |")
    return 1 if f else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except subprocess.TimeoutExpired as e:
        sys.exit(f"sigrok-cli timed out: {e}")
