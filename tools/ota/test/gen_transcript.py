#!/usr/bin/env python3
"""Record a byte-exact USB transcript of the reference DFU flasher.

Runs `slogicpt.dfu.spi_flash.flash_firmware` from the SLogic production-test
tools against a simulated USB-SPI bridge + SPI NOR flash, and writes every
bulk OUT payload and every bulk IN request/response as JSON. The web flasher's
test replays this transcript and must produce identical bytes.

    python3 gen_transcript.py <SLogic16U3-tools dir> <out.json> \
        [--size N] [--addr A] [--write-chunk W] [--read-chunk R]
"""
import argparse
import json
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tools_dir")
    ap.add_argument("out")
    ap.add_argument("--size", type=lambda s: int(s, 0), default=600)
    ap.add_argument("--addr", type=lambda s: int(s, 0), default=0x10000)
    ap.add_argument("--write-chunk", type=int, default=12)
    ap.add_argument("--read-chunk", type=int, default=64)
    args = ap.parse_args()

    sys.path.insert(0, args.tools_dir)
    from slogicpt.dfu import spi_flash

    events = []
    sim = FlashSim()

    class FakeUSB:
        def __init__(self, *a, **k):
            pass

        def write(self, data, timeout=None):
            data = bytes(data)
            events.append({"w": data.hex()})
            sim.on_write(data)
            return len(data)

        def read(self, size, timeout=None):
            data = sim.on_read(size)
            events.append({"r": size, "data": data.hex()})
            return data

        def close(self):
            pass

    spi_flash.USBDevice = FakeUSB

    class Ota:
        write_chunk = args.write_chunk
        read_chunk = args.read_chunk
        usb_timeout_ms = 1000
        wip_timeout_s = 5.0
        reset_settle_s = 0.0

    firmware = make_firmware(args.size)
    spi_flash.flash_firmware(0x359F, 0x30F1, args.addr, firmware, verify=True, ota=Ota)

    with open(args.out, "w") as f:
        json.dump({
            "addr": args.addr,
            "write_chunk": args.write_chunk,
            "read_chunk": args.read_chunk,
            "firmware": firmware.hex(),
            "events": events,
        }, f, separators=(",", ":"))
    print(f"{len(events)} events -> {args.out}", file=sys.stderr)


def make_firmware(size):
    """Deterministic image with an all-0xFF run (skipped by the programmer)."""
    out = bytearray()
    x = 0x12345678
    for i in range(size):
        x = (x * 1103515245 + 12345) & 0xFFFFFFFF
        out.append((x >> 16) & 0xFF)
    for i in range(min(size, 100), min(size, 200)):
        out[i] = 0xFF
    return bytes(out)


class FlashSim:
    """USB-SPI bridge + W25Q-style SPI NOR, enough for the flasher's commands."""

    CMD_SET_REGISTER = 0x00020000
    CMD_READ_REGISTER = 0x00020001
    CMD_READ_DATA = 0x00020002

    def __init__(self):
        self.mem = bytearray(b"\xA5" * (1 << 20))  # stale content: erase must happen
        self.wel = False
        self.wip_polls = 0
        self.pending = b""
        self.next_read = b""

    def on_write(self, pkt):
        cmd = int.from_bytes(pkt[0:4], "little")
        length = int.from_bytes(pkt[4:8], "little")
        data = pkt[8:8 + length]
        if cmd == self.CMD_SET_REGISTER:
            tc = int.from_bytes(data[8:12], "little")
            mode = (tc >> 24) & 0xF
            wr = ((tc >> 12) & 0x1FF) + 1
            rd = (tc & 0x1FF) + 1
            payload = data[40:]
            if mode == 7:
                self.pending = b""
            else:
                self.pending = self.spi(payload[:wr] if mode != 2 else b"",
                                        rd if mode in (2, 3, 5) else 0)
        elif cmd == self.CMD_READ_DATA:
            self.next_read = self.pending
            self.pending = b""
        elif cmd == self.CMD_READ_REGISTER:
            regs = bytearray(40)
            regs[28:32] = (0x00404000).to_bytes(4, "little")  # idle, FIFOs empty
            self.next_read = bytes(regs)

    def on_read(self, size):
        out, self.next_read = self.next_read[:size], b""
        return out

    def spi(self, wr, rd):
        op = wr[0] if wr else None
        addr = int.from_bytes(wr[1:4], "big") if len(wr) >= 4 else 0
        if op == 0x9F:
            return bytes([0xEF, 0x40, 0x18])[:rd]
        if op == 0x4B:
            return bytes(range(0x10, 0x10 + rd))
        if op == 0x06:
            self.wel = True
        elif op == 0x04:
            self.wel = False
        elif op == 0xD8 and self.wel:
            base = addr & ~0xFFFF
            self.mem[base:base + 0x10000] = b"\xFF" * 0x10000
            self.wip_polls = 2
            self.wel = False
        elif op == 0x02 and self.wel:
            for i, b in enumerate(wr[4:]):
                a = (addr & ~0xFF) | ((addr + i) & 0xFF)
                self.mem[a] &= b
            self.wip_polls = 1
            self.wel = False
        elif op == 0x05:
            if self.wip_polls:
                self.wip_polls -= 1
                return bytes([0x03])
            return bytes([0x02 if self.wel else 0x00])
        elif op == 0x0B:
            return bytes(self.mem[addr:addr + rd])
        return b""


if __name__ == "__main__":
    main()
