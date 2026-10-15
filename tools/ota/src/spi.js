// SLogic DFU: USB-SPI bridge protocol.
//
// In DFU mode the analyzer exposes one vendor interface with a bulk OUT and a
// bulk IN endpoint that drive an SPI master wired to the configuration flash.
// Every request is a packet  [u32 LE command][u32 LE length][payload]:
//
//   SET_REGISTER  0x00020000  payload = 40-byte register block (+ SPI TX bytes)
//   READ_REGISTER 0x00020001  device answers with the 40-byte register block
//   READ_DATA     0x00020002  device answers with the bytes clocked in by the
//                             last SPI transaction
//
// The register block is ten little-endian u32 words, in this order: Control,
// TransferFormat, TransferControl, InterruptEnable, Timing, InterruptStatus,
// Configuration, Status, Address, Command. This mirrors the reference flasher
// (SLogic production-test tools, slogicpt/dfu) byte for byte; see
// test/transcript-*.json.

export const CMD_SET_REGISTER = 0x00020000;
export const CMD_READ_REGISTER = 0x00020001;
export const CMD_READ_DATA = 0x00020002;

export const REGISTER_BLOCK_SIZE = 40;

const W_CONTROL = 0;
const W_TRANSFER_FORMAT = 1;
const W_TRANSFER_CONTROL = 2;
const W_TIMING = 4;
const W_CONFIGURATION = 6;
const W_STATUS = 7;

// TransferControl.TransMode
const MODE_WRITE_READ = 0x3;
const MODE_WRITE_ONLY = 0x1;
const MODE_READ_ONLY = 0x2;
const MODE_WRITE_DUMMY_READ = 0x5;
const MODE_NO_DATA = 0x7;

/** Register block with the bridge's power-on defaults. */
function defaultRegisters() {
  const w = new Uint32Array(10);
  w[W_TRANSFER_FORMAT] = (0x2 << 16) | (0x7 << 8) | (1 << 7); // AddrLen=2, DataLen=7, DataMerge
  w[W_TIMING] = (0x2 << 8) | 0xff;                             // CSHT=2, SCLK_DIV=0xFF
  w[W_CONFIGURATION] = (0x6 << 4) | 0x6;                       // TX/RX FIFO size
  w[W_STATUS] = (1 << 22) | (1 << 14);                         // TXEMPTY, RXEMPTY
  return w;
}

function transferControl({ mode, wrCnt = 0, rdCnt = 0, dummyCnt = 0 }) {
  return ((mode & 0xf) << 24) | ((wrCnt & 0x1ff) << 12) | ((dummyCnt & 0x3) << 9) | (rdCnt & 0x1ff);
}

function wordsToBytes(words) {
  const out = new Uint8Array(words.length * 4);
  const dv = new DataView(out.buffer);
  words.forEach((v, i) => dv.setUint32(i * 4, v >>> 0, true));
  return out;
}

export function packet(command, data = new Uint8Array(0)) {
  const out = new Uint8Array(8 + data.length);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, command, true);
  dv.setUint32(4, data.length, true);
  out.set(data, 8);
  return out;
}

function concat(...parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
}

export class BridgeError extends Error {}

/**
 * SPI master behind the DFU bulk endpoints.
 * `link` provides  write(Uint8Array) -> Promise<number>  and
 *                  read(n) -> Promise<Uint8Array>  (at most n bytes).
 */
export class SpiBridge {
  constructor(link) {
    this.link = link;
  }

  async readRegisters() {
    await this.link.write(packet(CMD_READ_REGISTER));
    const raw = await this.link.read(REGISTER_BLOCK_SIZE);
    if (raw.length < REGISTER_BLOCK_SIZE) {
      throw new BridgeError(`short register read (${raw.length} bytes)`);
    }
    return new DataView(raw.buffer, raw.byteOffset, raw.byteLength);
  }

  async setRegisters(words, payload = new Uint8Array(0)) {
    const pkt = packet(CMD_SET_REGISTER, concat(wordsToBytes(words), payload));
    const n = await this.link.write(pkt);
    if (n !== pkt.length) throw new BridgeError(`short write (${n}/${pkt.length} bytes)`);
  }

  async readData(n) {
    await this.link.write(packet(CMD_READ_DATA));
    return this.link.read(n);
  }

  /** After a transaction the bridge must be idle with an empty RX FIFO. */
  async assertIdle() {
    const status = (await this.readRegisters()).getUint32(W_STATUS * 4, true);
    const active = status & 1;
    const rxEmpty = (status >>> 14) & 1;
    if (active !== 0 || rxEmpty !== 1) {
      throw new BridgeError(`SPI bridge not idle (status 0x${status.toString(16).padStart(8, '0')})`);
    }
  }

  /** Reset the SPI core and both FIFOs. */
  async reset() {
    const w = defaultRegisters();
    w[W_CONTROL] = 0b111; // SPIRST | RXFIFORST | TXFIFORST
    w[W_TRANSFER_CONTROL] = transferControl({ mode: MODE_NO_DATA });
    await this.setRegisters(w);
  }

  /**
   * One SPI transaction: clock out `wr`, optionally `dummy` dummy bytes, then
   * clock in `rdN` bytes. Returns the bytes read.
   */
  async xfer(wr, rdN = 0, dummy = 0) {
    const wrN = wr.length;
    if (wrN === 0 && rdN === 0) return new Uint8Array(0);
    const padding = (4 - (wrN % 4)) % 4;
    const tx = new Uint8Array(wrN + padding).fill(0xff);
    tx.set(wr);

    let tc;
    if (rdN === 0) {
      tc = { mode: MODE_WRITE_ONLY, wrCnt: wrN - 1 };
    } else if (wrN === 0) {
      tc = { mode: MODE_READ_ONLY, rdCnt: rdN - 1 };
    } else if (dummy === 0 || dummy <= padding) {
      tc = { mode: MODE_WRITE_READ, wrCnt: wrN - 1 + dummy, rdCnt: rdN - 1 };
    } else {
      tc = { mode: MODE_WRITE_DUMMY_READ, wrCnt: wrN - 1 + padding, rdCnt: rdN - 1,
             dummyCnt: dummy - 1 - padding };
    }
    const w = defaultRegisters();
    w[W_TRANSFER_CONTROL] = transferControl(tc);
    await this.setRegisters(w, tx);

    let data = new Uint8Array(0);
    if (rdN) data = await this.readData(rdN);
    await this.assertIdle();
    return data;
  }
}
