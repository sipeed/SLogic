// SPI NOR flash operations over the DFU bridge, and the OTA sequence:
// check ID -> erase (64 KiB blocks) -> blank check -> program -> verify.
// The command sequence matches the reference flasher byte for byte
// (test/transcript-*.json), including skipping all-0xFF program chunks.

import { SpiBridge } from './spi.js';

export const ERASE_BLOCK = 0x10000;
const PAGE = 0x100;

export class FlashError extends Error {
  constructor(code, message, detail = {}) {
    super(message);
    this.code = code;
    this.detail = detail;
  }
}

export class AbortedError extends Error {
  constructor() {
    super('aborted');
    this.code = 'aborted';
  }
}

function addr24(a) {
  return [(a >>> 16) & 0xff, (a >>> 8) & 0xff, a & 0xff];
}

function hex(bytes) {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

export class SpiFlash {
  /**
   * @param link  {write(Uint8Array), read(n)} bulk transport
   * @param opts  writeChunk (bytes per page-program transaction), readChunk,
   *              wipTimeoutMs, signal (AbortSignal)
   */
  constructor(link, { writeChunk = 12, readChunk = 64, wipTimeoutMs = 5000, signal } = {}) {
    this.spi = new SpiBridge(link);
    this.writeChunk = Math.max(1, Math.min(PAGE, writeChunk));
    this.readChunk = Math.max(1, Math.min(512, readChunk));
    this.wipTimeoutMs = wipTimeoutMs;
    this.signal = signal;
  }

  checkAbort() {
    if (this.signal?.aborted) throw new AbortedError();
  }

  reset() { return this.spi.reset(); }
  readId() { return this.spi.xfer(Uint8Array.of(0x9f), 3); }
  readUid() { return this.spi.xfer(Uint8Array.of(0x4b), 16, 4); }

  async readData(addr, length, onProgress) {
    const out = new Uint8Array(length);
    let got = 0;
    while (got < length) {
      this.checkAbort();
      const need = Math.min(this.readChunk, length - got);
      const part = await this.spi.xfer(Uint8Array.of(0x0b, ...addr24(addr + got)), need, 1);
      if (part.length !== need) {
        throw new FlashError('short-read', `short read at 0x${(addr + got).toString(16)}`);
      }
      out.set(part, got);
      got += need;
      onProgress?.(got, length);
    }
    return out;
  }

  /** Run `op` with the write latch set, then wait for WIP to clear. */
  async withWriteEnable(op) {
    await this.spi.xfer(Uint8Array.of(0x06));
    try {
      await op();
    } catch (e) {
      await this.spi.xfer(Uint8Array.of(0x04)).catch(() => {});
      throw e;
    }
    const t0 = Date.now();
    for (;;) {
      const sr = (await this.spi.xfer(Uint8Array.of(0x05), 1))[0];
      if (sr === 0xff) {
        throw new FlashError('bus-hung', 'Flash status reads 0xFF: SPI bus not responding');
      }
      if (!(sr & 1)) break;
      if (Date.now() - t0 > this.wipTimeoutMs) {
        throw new FlashError('wip-timeout', 'Flash did not finish writing in time');
      }
    }
    await this.spi.xfer(Uint8Array.of(0x04));
  }

  eraseBlock(addr) {
    return this.withWriteEnable(() => this.spi.xfer(Uint8Array.of(0xd8, ...addr24(addr))));
  }

  async program(addr, data, onProgress) {
    let done = 0;
    while (done < data.length) {
      this.checkAbort();
      const a = addr + done;
      const room = PAGE - (a & 0xff); // page program wraps inside a 256-byte page
      const need = Math.min(this.writeChunk, room, data.length - done);
      const chunk = data.subarray(done, done + need);
      if (!chunk.every((b) => b === 0xff)) { // erased flash already reads 0xFF
        await this.withWriteEnable(() =>
          this.spi.xfer(Uint8Array.of(0x02, ...addr24(a), ...chunk)));
      }
      done += need;
      onProgress?.(done, data.length);
    }
  }
}

/**
 * The full update. `report({phase, done, total})` is called as work advances;
 * phases: 'check', 'erase', 'blank', 'program', 'verify', 'done'.
 * Throws FlashError / AbortedError / transport errors.
 */
export async function flashFirmware(flash, { addr = 0, firmware, verify = true, report = () => {} }) {
  if (addr % ERASE_BLOCK !== 0) {
    throw new FlashError('bad-addr', `Start address 0x${addr.toString(16)} is not 64 KiB aligned`);
  }
  const size = firmware.length;
  if (size === 0) throw new FlashError('empty', 'Firmware file is empty');

  report({ phase: 'check', done: 0, total: 1 });
  await flash.reset();
  let id = await flash.readId();
  if (hex(id) === 'ffffff' || hex(id) === '000000') {
    await flash.reset();
    id = await flash.readId();
    if (hex(id) === 'ffffff' || hex(id) === '000000') {
      throw new FlashError('no-flash', `Flash not responding (ID ${hex(id)})`, { id: hex(id) });
    }
  }
  const uid = await flash.readUid();
  const capacity = id[2] >= 16 && id[2] <= 28 ? 2 ** id[2] : 0;
  if (capacity && addr + size > capacity) {
    throw new FlashError('too-large',
      `Firmware (${size} bytes) does not fit the ${capacity / 1048576} MiB flash`,
      { size, capacity });
  }
  const info = { id: hex(id), uid: hex(uid), capacity };
  report({ phase: 'check', done: 1, total: 1, info });

  const blocks = Math.ceil(size / ERASE_BLOCK);
  for (let i = 0; i < blocks; i++) {
    flash.checkAbort();
    report({ phase: 'erase', done: i, total: blocks });
    await flash.eraseBlock(addr + i * ERASE_BLOCK);
  }
  report({ phase: 'erase', done: blocks, total: blocks });

  const erased = await flash.readData(addr, size,
    (done, total) => report({ phase: 'blank', done, total }));
  if (!erased.every((b) => b === 0xff)) {
    throw new FlashError('erase-failed', 'Flash is not blank after erase');
  }

  await flash.program(addr, firmware,
    (done, total) => report({ phase: 'program', done, total }));

  if (verify) {
    const back = await flash.readData(addr, size,
      (done, total) => report({ phase: 'verify', done, total }));
    const diff = back.findIndex((b, i) => b !== firmware[i]);
    if (diff >= 0) {
      throw new FlashError('verify-failed',
        `Verify failed: first difference at 0x${(addr + diff).toString(16)}`,
        { offset: addr + diff });
    }
  }
  report({ phase: 'done', done: 1, total: 1, info });
  return info;
}
