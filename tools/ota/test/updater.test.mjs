// End-to-end update against the demo WebUSB double: mode switching,
// authorization pauses and the flashed content.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { demoUsb } from '../src/demo.js';
import { MODELS, DFU_FILTERS, USB_FILTERS, identify } from '../src/devices.js';
import { runUpdate } from '../src/updater.js';

function image(size) {
  const fw = new Uint8Array(size);
  for (let i = 0; i < size; i++) fw[i] = i < 24 ? 0xff : (i * 31 + 7) & 0xff;
  return fw;
}

async function update(param, size) {
  const usb = demoUsb(param);
  const device = await usb.requestDevice({ filters: USB_FILTERS });
  const { model } = identify(device);
  const steps = [];
  const gestures = [];
  const firmware = image(size);
  const result = await runUpdate({
    usb, device, model, firmware,
    on: {
      step: (id, state) => steps.push(`${id}:${state}`),
      progress: () => {},
      log: () => {},
      gesture: async (kind) => {
        gestures.push(kind);
        return usb.requestDevice({ filters: DFU_FILTERS });
      },
    },
  });
  const written = usb.flash.mem.subarray(model.flashAddr, model.flashAddr + size);
  assert.ok(written.every((b, i) => b === firmware[i]), 'flash content matches the image');
  return { result, steps, gestures };
}

test('SLogic32U3: RECONFIG into update mode, flash, restart into the app', async () => {
  const { result, steps, gestures } = await update('32u3', 70000);
  assert.deepEqual(gestures, ['authorize-dfu']); // first time only: DFU device not yet authorized
  assert.deepEqual(steps, ['switch:active', 'switch:done', 'flash:active', 'flash:done',
    'restart:active', 'restart:done']);
  assert.equal(result.restarted, true);
  assert.equal(result.appDevice?.serialNumber, '202610150930');
});

test('SLogic16U3: manual switch to update mode, then a manual replug', async () => {
  const { result, steps, gestures } = await update('16u3', 70000);
  assert.deepEqual(gestures, ['manual-dfu']);
  assert.deepEqual(steps.slice(-2), ['restart:active', 'restart:manual']);
  assert.equal(result.restarted, false);
});
