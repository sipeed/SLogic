#!/usr/bin/env python3
"""SLogic32U3 cross-platform self-test over sigrok-cli.

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
    below real time, so throughput must be measured, not inferred;
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
(containing bin/sigrok-cli.exe), or a mounted macOS .app. Plug a SLogic32U3 into
the machine first. Exits non-zero if any check FAILS (or the device is missing,
unless --allow-no-device).
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import os
import re
import subprocess
import sys
import time
from pathlib import Path

DRIVER = "sipeed-slogic-analyzer"
MODEL = "SLogic32U3"
VENDOR_ID = "359f"
# channel mode -> max sample rate in MHz at USB 10G/SuperSpeed+ (source: slogic/slogic32u3.c).
# Aggregate wire rate = channels * MHz / 8 MB/s: 4ch@1400 = 700 MB/s, the rest = 800 MB/s.
# At USB 5G/SuperSpeed the sustainable aggregate halves, so the rates (and the standard) halve.
MODES_10G = [(4, 1400), (8, 800), (16, 400), (32, 200)]
STD_MBPS_10G = 800
DURATION_MS = 500           # per-mode capture; long enough for the sustained-rate average to settle
MIN_RATE_PCT = 90           # measured avg must reach this % of the expected per-mode rate
STRESS_ITERS = 20           # open/capture/close cycles for the leak/crash stress gate
CLAMP_RE = re.compile(r"wrap to|limit|not supported", re.IGNORECASE)
# driver -l 4 throughput line, e.g.:
#   ... Got 2000000000/2000000000(100.00%) => speed: 429.17MBps, 416.78MBps(avg), 800MBps(exp) => +116.513=4886.442ms.
SPEED_RE = re.compile(r"speed:\s*[\d.]+MBps,\s*([\d.]+)MBps\(avg\),\s*([\d.]+)MBps\(exp\)")
GOT_RE = re.compile(r"Got\s+(\d+)/\d+\(([\d.]+)%\)")   # bytes received, captured %
TIME_RE = re.compile(r"\+[\d.]+=([\d.]+)ms")            # cumulative device streaming time (ms)


def _bps_to_gen(bps: int) -> str:
    if bps >= 10_000_000_000:
        return "10G"
    if bps >= 5_000_000_000:
        return "5G"
    return "unknown"


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

    def counts(self) -> tuple[int, int, int]:
        st = [r[2] for r in self.rows]
        return st.count("PASS"), st.count("FAIL"), st.count("SKIP")


def timed(fn):
    t0 = time.monotonic()
    ok, detail = fn()
    return ("PASS" if ok else "FAIL"), detail, (time.monotonic() - t0) * 1000


# ------------------------------------------------------------------------ checks
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sigrok-cli", required=True, help="path to sigrok-cli (executable, portable dir, or .app)")
    ap.add_argument("--golden-dir", help="directory of <name>.sr + <name>.args + <name>.expected decode fixtures")
    ap.add_argument("--duration-ms", type=int, default=DURATION_MS,
                    help=f"per-mode capture duration in ms (default {DURATION_MS}; longer = steadier rate average)")
    ap.add_argument("--min-rate-pct", type=int, default=MIN_RATE_PCT,
                    help=f"measured avg rate must reach this %% of the expected per-mode rate (default {MIN_RATE_PCT})")
    ap.add_argument("--stress-iters", type=int, default=STRESS_ITERS,
                    help=f"open/capture/close cycles for the stress gate (default {STRESS_ITERS})")
    ap.add_argument("--usb-speed", choices=("10G", "5G"),
                    help="force the USB link speed standard (default: auto-detect); 5G halves rates + the MB/s standard")
    ap.add_argument("--allow-no-device", action="store_true", help="run device-independent checks only if no device is found")
    args = ap.parse_args()

    cli = resolve_cli(args.sigrok_cli)
    env = cli_env(cli)
    rep = Report()
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    info = {"date": started[:10], "platform": f"{sys.platform} ({os.name})", "os": sys.platform,
            "cli": str(cli), "sha256": _sha256(cli), "version": "?",
            "model": MODEL, "vidpid": "?", "serial": "?", "link": "?", "std": STD_MBPS_10G,
            "settings": f"duration {args.duration_ms}ms  min-rate {args.min_rate_pct}%"}
    print(f"SLogic32U3 self-test  |  {started}")
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
        return (rc == 0 and DRIVER in out), f"{DRIVER} " + ("present" if DRIVER in out else "MISSING")
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
    scan_detail = (f"{MODEL}  VID:PID {info['vidpid']}  S/N {info['serial']}" if device_present
                   else (scan_out.strip().splitlines()[0] if scan_out.strip() else "no device found"))
    rep.add("2.1", "scan", "PASS" if device_present else ("SKIP" if args.allow_no_device else "FAIL"),
            scan_detail, 0.0)

    if not device_present:
        if not args.allow_no_device:
            print("\nNo SLogic device found — connect a SLogic32U3 (or pass --allow-no-device).")
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

    # 2.3 USB link speed sets the aggregate throughput standard: 10G/SuperSpeed+ sustains the full
    # rates below (800 MB/s); 5G/SuperSpeed halves both the rates and the standard (400 MB/s).
    speed = args.usb_speed or detect_usb_speed()
    if speed == "5G":
        modes = [(ch, mhz // 2) for ch, mhz in MODES_10G]
        std = STD_MBPS_10G // 2
    else:
        modes = MODES_10G
        std = STD_MBPS_10G
    src = "forced" if args.usb_speed else ("auto" if speed != "unknown" else "undetected, assume 10G")
    info["link"], info["std"] = speed, std
    note = "" if speed != "unknown" else "; confirm manually / override with --usb-speed"
    print(f"  [----] 2.3  usb-link                  {speed} ({src}) - standard {std} MB/s{note}\n")

    # Real throughput test. The driver can "drain at the host's pace": when the USB link is slower
    # than the analyzer it still delivers every requested sample, just below real time — so a
    # complete capture is NOT proof of full speed. Capture at each mode's MAX rate with the driver's
    # -l 4 speed log, write the stream to the null device (so the disk is not the bottleneck), then
    # parse the driver's reported sustained average rate and require it to reach the expected
    # per-mode rate. That measured rate — not mere completeness — is the speed gate.
    cap_timeout = 120 + args.duration_ms * 60 // 1000

    def measure_rate(nch, mhz, pattern):
        """Capture to the null device with the -l 4 speed log.
        Returns ((avg, exp, captured%, volume_MB, device_ms), None) or (None, errmsg)."""
        samples = int(mhz * 1_000_000 * args.duration_ms / 1000)
        cfg = f"logic_channels={nch}:samplerate={mhz}m:pattern={pattern}"  # ':' separates settings
        rc, _, err = run(cli, env, ["-d", DRIVER, "-l", "4", "--config", cfg,
                                    "--samples", str(samples), "-O", "binary", "-o", os.devnull],
                         timeout=cap_timeout)
        if rc != 0:
            return None, f"rc={rc} {err.strip().splitlines()[-1] if err.strip() else ''}"
        speeds, gots, times = SPEED_RE.findall(err), GOT_RE.findall(err), TIME_RE.findall(err)
        if not speeds:
            return None, "driver reported no throughput (need -l 4 'speed:' lines)"
        avg, exp = float(speeds[-1][0]), float(speeds[-1][1])
        vol_mb = (int(gots[-1][0]) / 1e6) if gots else 0.0   # bytes received -> MB
        cap = float(gots[-1][1]) if gots else 0.0
        dev_ms = float(times[-1]) if times else 0.0          # device streaming time
        return (avg, exp, cap, vol_mb, dev_ms), None

    # Aligned columns so rates line up for an at-a-glance compare. The device streaming time +
    # volume let you sanity-check the rate by hand (volume / time ≈ avg).
    def fmt(avg, exp, pct, vol_mb, dev_ms, cap):
        return (f"{avg:6.1f} /{exp:6.1f} MB/s  {pct:4.0f}%   "
                f"{vol_mb:7.1f} MB  {dev_ms:7.1f} ms   {cap:5.1f}% cap")

    # Normal + Emulation at each mode's MAX rate: the sampled data rate must reach the expected rate.
    for nch, mhz in modes:
        for pat in ("Emulation", "Normal"):
            def c_rate(nch=nch, mhz=mhz, pat=pat):
                res, errmsg = measure_rate(nch, mhz, pat)
                if res is None:
                    return False, errmsg
                avg, exp, cap, vol_mb, dev_ms = res
                pct = (avg / exp * 100.0) if exp else 0.0
                detail = fmt(avg, exp, pct, vol_mb, dev_ms, cap)
                if cap < 99.9:
                    return False, "incomplete " + detail
                if pct < args.min_rate_pct:
                    return False, "SLOW       " + detail
                return True, detail
            rep.add("3.1", f"rate-{nch}ch@{mhz}MHz-{pat}", *timed(c_rate))

    # USB connection test (the max-speed pattern): raw link throughput, must reach or exceed the standard.
    def c_maxspeed():
        nch, mhz = modes[-1]
        res, errmsg = measure_rate(nch, mhz, "USB connection test")
        if res is None:
            return False, errmsg
        avg, _exp, cap, vol_mb, dev_ms = res
        pct = (avg / std * 100.0) if std else 0.0   # vs the aggregate standard, not the configured rate
        detail = fmt(avg, float(std), pct, vol_mb, dev_ms, cap)
        if cap < 99.9:
            return False, "incomplete " + detail
        if avg < std:
            return False, "below std  " + detail
        return True, detail
    rep.add("3.2", "maxspeed-USBtest", *timed(c_maxspeed))

    def c_clamp():
        cfg = "logic_channels=32:samplerate=1400m:pattern=Emulation"
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
    p, f, s = rep.counts()
    result = "FAIL" if f else "PASS"
    print(f"\n{'='*72}")
    print(f"PASS {p}   FAIL {f}   SKIP {s}   ->  RESULT: {result}")
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
