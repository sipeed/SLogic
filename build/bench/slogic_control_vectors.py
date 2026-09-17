#!/usr/bin/env python3
"""Golden control-transfer vectors for the SLogic U3 configure/run/stop path.

This is the control-sequence half of the libslogic conformance set (the packing
half is slogic_pack_ref.py).  It encodes the *canonical* ordered sequence of USB
vendor control transfers that `libslogic` must emit for one capture, plus the
two ways the current front ends diverge from it, so a captured register trace
(from `-l4`/`sr_dbg` or a libusb shim) can be diffed against a known-good
reference instead of eyeballed.

Derived by tracing both drivers for a SLogic32U3 at {16 ch, 200 MHz, Emulation,
1.7 V} and cross-checking:
  libsigrok  sources/libsigrok/src/hardware/sipeed-slogic-analyzer/{api,protocol}.c
  all-logic  sources/all-logic/libsigrok4DSL/hardware/sipeed-slogic/slogic16u3.c
See build/docs/slogic-protocol.md sections 2 and 6.7 for the canonical decision.

Transfer fields: op is WRITE (bRequest 0x01 REG_WRITE, bmRequestType 0x40) or
READ (bRequest 0x00 REG_READ, bmRequestType 0xC0).  wIndex is 0 on every
transfer.  Each transfer moves one 4-byte word; multi-word payloads step wValue
by +4 per word.  `data` is the 4 little-endian bytes for a WRITE; None for a
READ.  `note` marks device-dependent values (poll counts, the samplerate base
table, payload lengths) that a comparator must treat as wildcards.
"""

# Register addresses (protocol.md section 2).
R_CTRL = 0x0004
R_AUX = 0x000C
R_AUX_PAYLOAD = 0x0010  # R_AUX + 4

CTRL_STOP = bytes([0x00, 0x00, 0x00, 0x00])
CTRL_RUN = bytes([0x01, 0x00, 0x00, 0x00])
CTRL_RST = bytes([0x02, 0x00, 0x00, 0x00])  # never emitted on the capture path

# AUX command words (payload word 0 of the header write).
AUX_CHANNEL = 0x01
AUX_RATE = 0x02
AUX_VREF = 0x03
AUX_TEST = 0x05

W, R = "WRITE", "READ"


def _aux_block(cmd, payload_word0, *, confirm, extra_read_note=""):
    """One canonical AUX transaction (protocol.md section 2 + 6.7).

    write command word -> poll header until ready -> read payload ->
    write payload back -> (canonical) confirm read-back.
    """
    seq = [
        (W, R_AUX, bytes([cmd, 0, 0, 0]), f"AUX cmd {cmd}"),
        (R, R_AUX, None, "poll header until (h>>16)&1; 1-8 reads, device-dependent"),
        (R, R_AUX_PAYLOAD, None, "read old payload; word count = (h&0xffff)>>9" + extra_read_note),
        (W, R_AUX_PAYLOAD, payload_word0, "write payload word 0"),
    ]
    if confirm:
        seq.append((R, R_AUX_PAYLOAD, None, "confirm read-back (canonical: keep)"))
    return seq


# Config for the reference vector.
CH_COUNT = 16
CHANNEL_MASK = (1 << CH_COUNT) - 1                      # 0x0000FFFF
CHANNEL_MASK_LE = bytes([CHANNEL_MASK & 0xFF, (CHANNEL_MASK >> 8) & 0xFF,
                         (CHANNEL_MASK >> 16) & 0xFF, (CHANNEL_MASK >> 24) & 0xFF])
VTH_V = 1.7
DAC = round(VTH_V / 3.33 / 2.0 * 1024.0)                # 261 = 0x105, canonical rounds
DAC_LE = bytes([DAC & 0xFF, (DAC >> 8) & 0xFF, (DAC >> 16) & 0xFF, (DAC >> 24) & 0xFF])
TEST_EMULATION = bytes([0x02, 0x00, 0x00, 0x00])        # mode 2

# --- CANONICAL sequence (protocol.md 6.7): STOP, then channel, samplerate,
# vref, pattern in fixed order each with a confirm read-back, then RUN. ---
CANONICAL_RUN = (
    [(W, R_CTRL, CTRL_STOP, "CTRL=STOP (pre-arm)")]
    + _aux_block(AUX_CHANNEL, CHANNEL_MASK_LE, confirm=True)
    + _aux_block(AUX_RATE, None, confirm=True,
                 extra_read_note="; rate payload is 8 bytes: [u16 base_idx][u16 base_mhz][u32 div]")
    + _aux_block(AUX_VREF, DAC_LE, confirm=True)
    + _aux_block(AUX_TEST, TEST_EMULATION, confirm=True)
    + [(W, R_CTRL, CTRL_RUN, "CTRL=RUN")]
)
# The samplerate block's payload-1 write is `div = base_mhz*1e6/want - 1`,
# device-dependent on which base the firmware table yields (e.g. base 800 MHz
# @200 MHz -> div word = 03 00 00 00).  Marked device-dependent above.

CANONICAL_STOP = [(W, R_CTRL, CTRL_STOP, "CTRL=STOP; deferred until bulk URBs drain")]

# --- Observed divergences from canonical, for the conformance diff. Neither
# changes the register *values* written, only ordering / extra reads. ---
DIVERGENCES = {
    "libsigrok": [
        "pattern (AUX cmd 5) is applied at config-set time, BEFORE the "
        "STOP/channel/rate/vref/RUN block, not after vref",
        "confirms every AUX write with a read-back (matches canonical)",
        "vref confirm compares read-back against a hard-coded 1024 (api.c:1154), "
        "so it always logs a false 'Failed to configure vref' (benign)",
        "VTH DAC truncates instead of rounding (may differ by 1 code)",
    ],
    "all-logic": [
        "pattern (AUX cmd 5) is applied LAST, after vref and before RUN "
        "(this is the canonical order)",
        "skips the confirm read-back on channel/vref/test (only samplerate "
        "re-reads); canonical adds them back",
    ],
}


def format_seq(seq):
    lines = []
    for i, (op, wval, data, note) in enumerate(seq, 1):
        d = " ".join(f"{b:02X}" for b in data) if data is not None else "--"
        lines.append(f"{i:2d}. {op:5s} wValue=0x{wval:04X} data=[{d:>11}]  {note}")
    return "\n".join(lines)


if __name__ == "__main__":
    assert DAC == 261, DAC
    assert CHANNEL_MASK_LE == bytes([0xFF, 0xFF, 0x00, 0x00]), CHANNEL_MASK_LE
    # Canonical RUN must start with STOP and end with RUN, and write exactly one
    # of each CTRL word plus four AUX command words (channel/rate/vref/test).
    assert CANONICAL_RUN[0][2] == CTRL_STOP
    assert CANONICAL_RUN[-1][2] == CTRL_RUN
    aux_cmds = [d[0] for (op, wv, d, n) in CANONICAL_RUN
                if op == W and wv == R_AUX and d is not None]
    assert aux_cmds == [AUX_CHANNEL, AUX_RATE, AUX_VREF, AUX_TEST], aux_cmds
    # RST = CTRL_RST written to R_CTRL specifically; note AUX cmd 2 (rate) has
    # the same byte value 02 00 00 00 but targets R_AUX, so match on register.
    assert not any(op == W and wv == R_CTRL and d == CTRL_RST
                   for (op, wv, d, n) in CANONICAL_RUN), "RST must never appear"
    print("SLogic32U3 {16ch, 200MHz, Emulation, 1.7V} — canonical RUN sequence:")
    print(format_seq(CANONICAL_RUN))
    print("\ncanonical STOP sequence:")
    print(format_seq(CANONICAL_STOP))
    print("\nknown per-driver divergences (conformance diff):")
    for drv, items in DIVERGENCES.items():
        print(f"  {drv}:")
        for it in items:
            print(f"    - {it}")
    print("\nall control-vector assertions pass")
