#!/usr/bin/env python3
"""Generate the golden decode fixtures for slogic_selftest.py check 4.1.

Writes sigrok session files (srzip v2) with synthetic, bit-exact UART, SPI
and I2C traffic, each with an `.args` sidecar (the sigrok-cli decoder
arguments). No signal generator is needed. The `.expected` sidecars are the
decoder output, bootstrapped once with a known-good sigrok-cli and checked by
hand against the payload printed here, then committed:

    python3 build/bench/make_golden_sr.py build/bench/golden
    python3 build/bench/make_golden_sr.py build/bench/golden \\
        --bootstrap <sigrok-cli>      # writes .expected, prints them for review

Stdlib only; deterministic output.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from pathlib import Path

RATE_HZ = 1_000_000          # 1 MHz sample clock
NCH = 8                      # D0..D7, unitsize 1


class Trace:
    """Samples as one byte each (bit i = Di); all lines start high."""

    def __init__(self, idle: int = 0xFF):
        self.level = idle
        self.samples = bytearray()

    def hold(self, n: int) -> None:
        self.samples += bytes([self.level]) * n

    def set(self, ch: int, v: int) -> None:
        self.level = (self.level | (1 << ch)) if v else (self.level & ~(1 << ch))


def uart(text: bytes, baud: int = 115200) -> Trace:
    t = Trace()
    bit = RATE_HZ / baud
    acc = 0.0
    t.hold(200)

    def emit(v: int) -> None:
        nonlocal acc
        t.set(0, v)
        acc += bit
        n = int(acc)
        acc -= n
        t.hold(n)

    for ch in text:
        emit(0)                                  # start
        for i in range(8):                       # data, LSB first
            emit((ch >> i) & 1)
        emit(1)                                  # stop
    t.hold(200)
    return t


def spi(mosi: bytes, miso: bytes, half: int = 4) -> Trace:
    """Mode 0: CLK D0 idle low, MOSI D1, MISO D2, CS# D3."""
    t = Trace()
    t.set(0, 0)
    t.hold(100)
    t.set(3, 0)                                  # CS# low
    t.hold(half)
    for mo, mi in zip(mosi, miso):
        for i in range(7, -1, -1):               # MSB first
            t.set(1, (mo >> i) & 1)
            t.set(2, (mi >> i) & 1)
            t.hold(half)                         # setup, clock low
            t.set(0, 1)
            t.hold(half)                         # sample on the rising edge
            t.set(0, 0)
    t.hold(half)
    t.set(3, 1)                                  # CS# high
    t.hold(100)
    return t


def i2c(addr: int, data: bytes, q: int = 2) -> Trace:
    """100 kHz-ish write: SCL D0, SDA D1, every byte ACKed."""
    t = Trace()
    t.hold(100)
    t.set(1, 0)                                  # START: SDA falls, SCL high
    t.hold(q * 2)
    t.set(0, 0)
    t.hold(q)

    def byte(v: int) -> None:
        for i in range(7, -1, -1):
            t.set(1, (v >> i) & 1)
            t.hold(q)
            t.set(0, 1)
            t.hold(q * 2)
            t.set(0, 0)
            t.hold(q)
        t.set(1, 0)                              # ACK from the target
        t.hold(q)
        t.set(0, 1)
        t.hold(q * 2)
        t.set(0, 0)
        t.hold(q)

    byte((addr << 1) | 0)                        # address + write
    for v in data:
        byte(v)
    t.set(1, 0)
    t.hold(q)
    t.set(0, 1)
    t.hold(q * 2)
    t.set(1, 1)                                  # STOP: SDA rises, SCL high
    t.hold(100)
    return t


def write_sr(path: Path, trace: Trace) -> None:
    meta = "\n".join([
        "[global]",
        "sigrok version=0.6.0",
        "",
        "[device 1]",
        "capturefile=logic-1",
        f"total probes={NCH}",
        f"samplerate={RATE_HZ // 1_000_000} MHz",
        "total analog=0",
        *[f"probe{i + 1}=D{i}" for i in range(NCH)],
        "unitsize=1",
        "",
    ])
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (("version", b"2"), ("metadata", meta.encode()),
                           ("logic-1-1", bytes(trace.samples))):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)


FIXTURES = {
    "uart_115200": (lambda: uart(b"SLogic 2.3.0\r\n"),
                    "-P uart:rx=D0:baudrate=115200 -A uart=rx-data",
                    'UART rx bytes of "SLogic 2.3.0\\r\\n"'),
    "spi_mode0": (lambda: spi(bytes([0x9F, 0x00, 0x00, 0x00, 0xA5, 0x5A, 0x01, 0x80]),
                              bytes([0xFF, 0xEF, 0x40, 0x18, 0x00, 0x11, 0x22, 0x33])),
                  "-P spi:clk=D0:mosi=D1:miso=D2:cs=D3 -A spi=mosi-data",
                  "SPI MOSI 9F 00 00 00 A5 5A 01 80"),
    "i2c_write": (lambda: i2c(0x50, bytes([0xA5, 0x5A, 0x3C])),
                  "-P i2c:scl=D0:sda=D1 -A i2c=address-write:data-write",
                  "I2C write to 0x50: A5 5A 3C"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outdir")
    ap.add_argument("--bootstrap", metavar="SIGROK_CLI",
                    help="also write .expected using this sigrok-cli (review before committing)")
    a = ap.parse_args()
    out = Path(a.outdir)
    out.mkdir(parents=True, exist_ok=True)
    for name, (make, args, payload) in FIXTURES.items():
        sr = out / f"{name}.sr"
        write_sr(sr, make())
        (out / f"{name}.args").write_text(args + "\n", encoding="utf-8")
        print(f"{sr}: {payload}")
        if a.bootstrap:
            cp = subprocess.run([a.bootstrap, "-i", str(sr), *args.split()],
                                capture_output=True, text=True)
            if cp.returncode != 0:
                print(cp.stderr, file=sys.stderr)
                return 1
            (out / f"{name}.expected").write_text(cp.stdout.strip() + "\n", encoding="utf-8")
            print("  " + cp.stdout.strip().replace("\n", "\n  "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
