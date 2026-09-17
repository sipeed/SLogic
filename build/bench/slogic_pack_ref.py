#!/usr/bin/env python3
"""Standalone reference decoder for the SLogic sample-major wire format.

The wire stream is sample-major: each decoded value is the parallel state of
the enabled channels (bit i = channel Di, LSB = D0).  This module implements
the *shared decode* of two reference C implementations, which agree exactly on
the ordered sample sequence produced from raw wire bytes (they only differ in
how they reshape that sequence downstream):

  libsigrok  sources/libsigrok/src/hardware/sipeed-slogic-analyzer/api.c
             slogic_submit_raw_data(), nCh<8 byte-expansion path:
               nsp_in_bytes = 8 / nCh;
               ptr[i*nsp + j] = (data[i + j/nsp] >> (j%nsp * nCh)) & ((1<<nCh)-1);
             For nCh>=8 it does NOT repack: it forwards the raw bytes with
             unitsize=(nCh+7)/8, i.e. host little-endian per sample.

  all-logic  sources/all-logic/libsigrok4DSL/hardware/sipeed-slogic/slogic16u3.c
             slogic_unpack_append():
               nCh<8:  ((uint32_t)b >> (i * nch)) & mask   for i in 0..samples_per_byte-1
               nCh>=8: s |= (uint32_t)p[i] << (8 * i)      little-endian

Sub-byte / byte ordering (decisive citations):
  * 2ch: 4 samples/byte, sample k = (byte >> (2*k)) & 0x3, sample 0 is the LOW
    two bits.  Proof: all-logic `(b >> (i*nch)) & mask` with i=0 -> shift 0.
  * 4ch: 2 samples/byte, sample 0 = LOW nibble (byte & 0xF), sample 1 = HIGH
    nibble (byte >> 4).  Proof: same expression, nch=4, i=0 shift 0, i=1 shift 4.
  * 8ch: 1 byte per sample.
  * 16ch: 2 bytes LITTLE-ENDIAN, sample = b0 | (b1 << 8).  Proof: all-logic
    `s |= (uint32_t)p[i] << (8*i)`; i=0 is the low byte.
  * 32ch: 4 bytes LITTLE-ENDIAN, sample = b0 | b1<<8 | b2<<16 | b3<<24.
"""


def decode(nch, raw):
    """Decode raw wire bytes (bytes/bytearray/list-of-int) for nch channels.

    Returns the ordered list of parallel sample values as ints.
    Trailing bytes that cannot form a whole sample are ignored (as the C does).
    """
    raw = bytes(raw)
    if nch < 1:
        raise ValueError("nch must be >= 1")

    if nch < 8:
        samples_per_byte = 8 // nch          # 4 (2ch) or 2 (4ch)
        mask = (1 << nch) - 1
        out = []
        for b in raw:
            for i in range(samples_per_byte):
                out.append((b >> (i * nch)) & mask)
        return out

    bytes_per_sample = (nch + 7) // 8         # 1, 2 or 4
    out = []
    for off in range(0, len(raw) - bytes_per_sample + 1, bytes_per_sample):
        s = 0
        for i in range(bytes_per_sample):     # little-endian
            s |= raw[off + i] << (8 * i)
        out.append(s)
    return out


# --- hand-checkable conformance vectors: (nch, raw_bytes, expected_samples) ---
VECTORS = [
    # 2ch: 0xE4 = 11 10 01 00 -> low-first -> 0,1,2,3 ; 0x1B -> 3,2,1,0
    (2,  [0xE4, 0x1B],                               [0, 1, 2, 3, 3, 2, 1, 0]),
    # 4ch: low nibble is sample 0. 0x3A -> A,3 ; 0xF1 -> 1,F
    (4,  [0x3A, 0xF1],                               [0xA, 0x3, 0x1, 0xF]),
    # 8ch: one byte per sample
    (8,  [0x00, 0x80, 0x7F, 0xFF],                   [0x00, 0x80, 0x7F, 0xFF]),
    # 16ch: little-endian. [34,12]->0x1234 ; [FF,00]->0x00FF
    (16, [0x34, 0x12, 0xFF, 0x00],                   [0x1234, 0x00FF]),
    # 32ch: little-endian. [78,56,34,12]->0x12345678 ; [00,00,00,80]->0x80000000
    (32, [0x78, 0x56, 0x34, 0x12, 0x00, 0x00, 0x00, 0x80],
                                                     [0x12345678, 0x80000000]),
]


if __name__ == "__main__":
    for nch, raw, expected in VECTORS:
        got = decode(nch, raw)
        raw_hex = " ".join(f"{b:02X}" for b in raw)
        width = (nch + 3) // 4
        got_hex = "[" + ", ".join(f"0x{v:0{width}X}" for v in got) + "]"
        assert got == expected, (
            f"{nch}ch MISMATCH: raw={raw_hex} got={got} expected={expected}")
        print(f"{nch:2d}ch  raw=[{raw_hex}]  ->  {got_hex}  OK")
    print("all vectors pass")
