// Replays transcripts recorded from the reference Python flasher
// (test/gen_transcript.py) and checks the web flasher sends identical bytes.
//
//   node --test test/

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { SpiFlash, flashFirmware, FlashError } from '../src/flash.js';

const fromHex = (h) => Uint8Array.from(h.match(/../g) ?? [], (x) => parseInt(x, 16));
const toHex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');

function load(name) {
  const url = name.startsWith('/') ? name : new URL(name, import.meta.url);
  return JSON.parse(readFileSync(url, 'utf8'));
}

// Extra transcripts (e.g. a multi-block image from gen_transcript.py --size
// 0x10200): EXTRA_TRANSCRIPTS=/abs/a.json:/abs/b.json node --test test/
const extra = (process.env.EXTRA_TRANSCRIPTS ?? '').split(':').filter(Boolean);

class ReplayLink {
  constructor(events, mutate = (i, e) => e) {
    this.events = events;
    this.mutate = mutate;
    this.i = 0;
  }
  next() {
    const i = this.i++;
    if (i >= this.events.length) assert.fail(`transport used past the transcript end (event ${i})`);
    return [i, this.mutate(i, this.events[i])];
  }
  async write(data) {
    const [i, e] = this.next();
    assert.ok(e.w !== undefined, `event ${i}: expected a read of ${e.r}, got a write ${toHex(data)}`);
    assert.equal(toHex(data), e.w, `event ${i}: OUT payload differs`);
    return data.length;
  }
  async read(n) {
    const [i, e] = this.next();
    assert.ok(e.r !== undefined, `event ${i}: expected write ${e.w}, got a read of ${n}`);
    assert.equal(n, e.r, `event ${i}: IN length differs`);
    return fromHex(e.data);
  }
}

for (const name of ['transcript-16u3.json', 'transcript-32u3.json', ...extra]) {
  test(`byte-identical to the reference flasher: ${name}`, async () => {
    const t = load(name);
    const link = new ReplayLink(t.events);
    const flash = new SpiFlash(link, { writeChunk: t.write_chunk, readChunk: t.read_chunk });
    const phases = new Set();
    const info = await flashFirmware(flash, {
      addr: t.addr, firmware: fromHex(t.firmware), report: (r) => phases.add(r.phase),
    });
    assert.equal(link.i, t.events.length, 'transcript not fully consumed');
    assert.equal(info.id, 'ef4018');
    assert.deepEqual([...phases], ['check', 'erase', 'blank', 'program', 'verify', 'done']);
  });
}

test('a readback mismatch is reported with its offset', async () => {
  const t = load('transcript-16u3.json');
  const firmware = fromHex(t.firmware);
  // Corrupt the last data read (part of verify).
  const last = t.events.map((e, i) => [e, i]).filter(([e]) => e.r && e.r > 1 && e.r !== 40).pop()[1];
  const link = new ReplayLink(t.events, (i, e) => {
    if (i !== last) return e;
    const d = fromHex(e.data);
    d[0] ^= 0x01;
    return { ...e, data: toHex(d) };
  });
  const flash = new SpiFlash(link, { writeChunk: t.write_chunk, readChunk: t.read_chunk });
  await assert.rejects(flashFirmware(flash, { addr: t.addr, firmware }),
    (e) => e instanceof FlashError && e.code === 'verify-failed');
});

test('a hung bus (status 0xFF) stops instead of waiting forever', async () => {
  const t = load('transcript-16u3.json');
  // First status-register poll answer -> 0xFF.
  const sr = t.events.findIndex((e, i) => e.r === 1 && t.events[i - 2]?.w?.endsWith('05ffffff'));
  const link = new ReplayLink(t.events, (i, e) => (i === sr ? { ...e, data: 'ff' } : e));
  const flash = new SpiFlash(link, { writeChunk: t.write_chunk, readChunk: t.read_chunk });
  await assert.rejects(flashFirmware(flash, { addr: t.addr, firmware: fromHex(t.firmware) }),
    (e) => e instanceof FlashError && e.code === 'bus-hung');
});

test('abort stops between transactions', async () => {
  const t = load('transcript-32u3.json');
  const ac = new AbortController();
  const link = new ReplayLink(t.events);
  const flash = new SpiFlash(link, { writeChunk: t.write_chunk, readChunk: t.read_chunk, signal: ac.signal });
  await assert.rejects(flashFirmware(flash, {
    addr: t.addr, firmware: fromHex(t.firmware),
    report: (r) => { if (r.phase === 'program') ac.abort(); },
  }), (e) => e.code === 'aborted');
});
