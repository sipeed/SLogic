// The firmware version table (firmware.json): read by the release notes
// ({{firmware.<model>.<field>}}) and by pages that warn about old firmware.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { MODELS, VID } from '../src/devices.js';

const table = JSON.parse(readFileSync(new URL('../firmware.json', import.meta.url), 'utf8'));
const version = /^\d{12}$/; // YYYYMMDDHHMM, the normal-mode USB serial number

test('every model has a well-formed entry', () => {
  assert.equal(table.schema, 1);
  assert.deepEqual(Object.keys(table.models).sort(), Object.keys(MODELS).sort());
  for (const [id, m] of Object.entries(table.models)) {
    const hex = (n) => n.toString(16).padStart(4, '0');
    assert.equal(m.name, MODELS[id].name);
    assert.equal(m.usb.app, `${hex(VID)}:${hex(MODELS[id].appPid)}`);
    assert.equal(m.usb.dfu, `${hex(VID)}:${hex(MODELS[id].dfuPid)}`);
    for (const f of ['min', 'latest']) assert.ok(m[f] === null || version.test(m[f]), `${id}.${f}`);
    if (m.min && m.latest) assert.ok(m.min <= m.latest, `${id}: min after latest`);
  }
});
