// Batch engine against several simulated boards at once.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { demoUsb } from '../src/demo.js';
import { MODELS } from '../src/devices.js';
import { BatchEngine } from '../src/batch-engine.js';

function image(size) {
  const fw = new Uint8Array(size);
  for (let i = 0; i < size; i++) fw[i] = i < 24 ? 0xff : (i * 13 + 5) & 0xff;
  return fw;
}

function until(engine, pred, ms = 60000) {
  return new Promise((resolve, reject) => {
    const check = () => {
      if (pred()) { engine.removeEventListener('change', check); clearTimeout(t); resolve(); }
    };
    const t = setTimeout(() => {
      engine.removeEventListener('change', check);
      reject(new Error(`timed out; states: ${engine.boards.map((b) => `#${b.id}:${b.state}:${b.message}`).join(' ')}`));
    }, ms);
    engine.addEventListener('change', check);
    check();
  });
}

const states = (e) => e.boards.map((b) => b.state);

test('SLogic32U3 batch: boards in both modes are updated in parallel and restarted', async () => {
  const usb = demoUsb('32u3', { permitAll: true, boards: 0 });
  usb.plug('slogic32u3', 'dfu', true);
  usb.plug('slogic32u3', 'dfu', true);
  usb.plug('slogic32u3', 'app', true);
  const firmware = image(70000);
  const engine = new BatchEngine({ usb });
  await engine.attach();
  engine.configure({ model: MODELS.slogic32u3, firmware, updateNormal: true });
  assert.deepEqual(states(engine), ['ready', 'ready', 'waiting']);

  engine.start();
  await until(engine, () => states(engine).every((s) => s === 'done'));
  assert.equal(engine.boards.length, 3, 'restarted boards are matched, not added as new ones');
  assert.equal(engine.targetSerial, '202610150930');
  for (const board of usb.boards) {
    assert.ok(board.flash.mem.subarray(0, firmware.length).every((b, i) => b === firmware[i]));
  }

  // Operator swaps a finished board for a blank one.
  usb.unplug(engine.boards[0].device);
  assert.equal(engine.boards[0].state, 'removed');
  usb.plug('slogic32u3', 'dfu');
  await until(engine, () => engine.boards.length === 4 && engine.boards[3].state === 'done');
  assert.equal(engine.counts().total, 4);

  // A board that already runs the new firmware is not flashed again.
  const fresh = usb.plug('slogic32u3', 'app', true);
  fresh.serialNumber = '202610150930';
  engine.add(fresh);
  assert.equal(engine.boards.at(-1).state, 'done');
  assert.equal(engine.counts().total, 4, 'an up-to-date board is not counted');
  engine.detach();
});

test('SLogic16U3 batch: update-mode boards are flashed and marked for a replug; wrong model is flagged', async () => {
  const usb = demoUsb('16u3', { permitAll: true, boards: 0 });
  usb.plug('slogic16u3', 'dfu', true);
  usb.plug('slogic16u3', 'app', true);
  usb.plug('slogic32u3', 'dfu', true);
  const engine = new BatchEngine({ usb });
  await engine.attach();
  engine.configure({ model: MODELS.slogic16u3, firmware: image(40000) });
  engine.start();
  await until(engine, () => engine.boards[0].state === 'done');
  assert.equal(engine.boards[0].message, 'replug');
  assert.equal(engine.boards[1].state, 'waiting');
  assert.equal(engine.boards[1].message, 'press-mode');
  assert.equal(engine.boards[2].state, 'wrong-model');
  engine.detach();
});

async function batch(modelId, firmwareSize = 40000) {
  const usb = demoUsb(modelId === 'slogic16u3' ? '16u3' : '32u3', { permitAll: true, boards: 0 });
  const engine = new BatchEngine({ usb });
  await engine.attach();
  engine.configure({ model: MODELS[modelId], firmware: image(firmwareSize) });
  engine.start();
  return { usb, engine };
}

test('a finished board that drops off the bus and comes back keeps its row and is counted once', async () => {
  const { usb, engine } = await batch('slogic32u3');
  usb.plug('slogic32u3', 'dfu');
  await until(engine, () => engine.boards[0]?.state === 'done');
  assert.equal(engine.counts().total, 1);
  for (let i = 0; i < 3; i++) {
    await usb.reconnect(engine.boards[0].device);
    await until(engine, () => engine.boards[0].state === 'done');
  }
  assert.equal(engine.boards.length, 1, 'no new rows for a flickering board');
  assert.equal(engine.counts().total, 1, 'session total unchanged');
  // An up-to-date board plugged in fresh is shown but not counted.
  const other = usb.plug('slogic32u3', 'app', true);
  other.serialNumber = engine.targetSerial;
  engine.add(other);
  assert.equal(engine.boards.at(-1).message, 'already');
  assert.equal(engine.counts().total, 1);
  engine.detach();
});

test('a write error is retried automatically and the board still finishes', async () => {
  const { usb, engine } = await batch('slogic32u3');
  usb.plug('slogic32u3', 'dfu', true).board.failIn = 400;
  engine.add(usb.devices.at(-1));
  await until(engine, () => engine.boards[0].state === 'retrying');
  await until(engine, () => engine.boards[0].state === 'done');
  assert.equal(engine.counts().total, 1);
  engine.detach();
});

test('a board that keeps failing ends as failed after the retries; nothing else is in progress', async () => {
  const { usb, engine } = await batch('slogic16u3');
  const d = usb.plug('slogic16u3', 'dfu', true);
  d.board.failIn = 300;
  d.board.failRepeat = 300;
  engine.add(d);
  await until(engine, () => engine.boards[0].state === 'failed', 30000);
  assert.equal(engine.boards[0].attempts, 3);
  const c = engine.counts();
  assert.deepEqual([c.failed, c.active, c.total], [1, 0, 0]);
  engine.detach();
});

test('a board unplugged mid-update continues on the same row when plugged back in', async () => {
  const { usb, engine } = await batch('slogic16u3');
  usb.plug('slogic16u3', 'dfu');
  await until(engine, () => engine.boards[0]?.phase === 'program');
  const back = usb.reconnect(engine.boards[0].device, 200);
  await until(engine, () => engine.boards[0].message === 'interrupted');
  await back;
  await until(engine, () => engine.boards.length === 1 && engine.boards[0].state === 'done');
  assert.equal(engine.boards[0].id, 1);
  assert.equal(engine.counts().total, 1);
  // A finished 16U3 (still in update mode) that reconnects is not written again.
  const writes = engine.boards[0].finished;
  await usb.reconnect(engine.boards[0].device);
  await until(engine, () => engine.boards.length === 1 && engine.boards[0].state === 'done');
  assert.equal(engine.boards[0].finished, writes);
  assert.equal(engine.counts().total, 1);
  engine.detach();
});

test('by default a board in normal mode is left alone', async () => {
  const usb = demoUsb('32u3', { permitAll: true, boards: 0 });
  const engine = new BatchEngine({ usb });
  await engine.attach();
  engine.configure({ model: MODELS.slogic32u3, firmware: image(40000) });
  engine.start();
  usb.plug('slogic32u3', 'app');
  await new Promise((r) => setTimeout(r, 1500));
  assert.equal(engine.boards[0].state, 'waiting');
  assert.equal(usb.devices[0].productId, MODELS.slogic32u3.appPid, 'not switched to update mode');
  engine.detach();
});
