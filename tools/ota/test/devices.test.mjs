// Model identification and firmware sanity checks.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MODELS, identify, inspectFirmware, VID } from '../src/devices.js';

const dev = (productId) => ({ vendorId: VID, productId });
const image = (size) => { const b = new Uint8Array(size); b.fill(0xff, 0, 24); return b; };

test('identifies both models in both modes', () => {
  assert.deepEqual(identify(dev(0x3031)), { model: MODELS.slogic16u3, mode: 'app' });
  assert.deepEqual(identify(dev(0x30f1)), { model: MODELS.slogic16u3, mode: 'dfu' });
  assert.deepEqual(identify(dev(0x3032)), { model: MODELS.slogic32u3, mode: 'app' });
  assert.deepEqual(identify(dev(0x30f2)), { model: MODELS.slogic32u3, mode: 'dfu' });
  assert.equal(identify({ vendorId: 0x1234, productId: 0x3031 }), null);
});

test('an early 32U3 on the shared DFU ID stays a 32U3, with the safe chunk size', () => {
  const r = identify(dev(0x30f1), MODELS.slogic32u3);
  assert.equal(r.model.id, 'slogic32u3');
  assert.equal(r.model.writeChunk, MODELS.slogic16u3.writeChunk);
});

test('firmware warnings', () => {
  assert.deepEqual(inspectFirmware(image(1715588), 'slogic32u3_lp13.bin', MODELS.slogic32u3), []);
  assert.deepEqual(inspectFirmware(image(496484), 'app.bin', MODELS.slogic16u3), []);
  assert.deepEqual(inspectFirmware(image(496484), 'app.bin', MODELS.slogic32u3), ['size-unusual']);
  assert.deepEqual(inspectFirmware(image(1715588), 'slogic16u3.bin', MODELS.slogic32u3), ['name-other-model']);
  assert.deepEqual(inspectFirmware(new Uint8Array(4096), 'x.bin', MODELS.slogic32u3), ['not-bitstream', 'size-unusual']);
});
