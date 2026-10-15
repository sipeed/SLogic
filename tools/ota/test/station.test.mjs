// Station setup files for the browser policy.

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { stationFiles, policyValue } from '../src/station.js';

const ORIGIN = 'https://ota.example.com';
const expected = policyValue(ORIGIN);

test('policy lists both models in both modes for the page origin', () => {
  assert.deepEqual(expected[0].urls, [ORIGIN]);
  assert.deepEqual(expected[0].devices.map((d) => d.product_id.toString(16)).sort(), ['3031', '3032', '30f1', '30f2']);
  assert.ok(expected[0].devices.every((d) => d.vendor_id === 0x359f));
});

test('Windows .reg installs the JSON for Chrome and Edge and removes it again', () => {
  const { install, remove } = stationFiles('windows', ORIGIN);
  assert.match(install.text, /^Windows Registry Editor Version 5\.00\r\n/);
  const values = [...install.text.matchAll(/^"WebUsbAllowDevicesForUrls"="(.*)"\r$/gm)].map((m) => m[1]);
  assert.equal(values.length, 2);
  for (const v of values) assert.deepEqual(JSON.parse(v.replace(/\\"/g, '"').replace(/\\\\/g, '\\')), expected);
  assert.match(install.text, /\[HKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\Google\\Chrome\]/);
  assert.match(install.text, /\[HKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\Microsoft\\Edge\]/);
  assert.equal(remove.text.match(/"WebUsbAllowDevicesForUrls"=-/g).length, 2);
});

test('Linux script carries the policy JSON and the udev rule; macOS profile embeds the policy', () => {
  const { install, remove } = stationFiles('linux', ORIGIN);
  const json = install.text.match(/<<'EOF'\n([\s\S]*?)\nEOF/)[1];
  assert.deepEqual(JSON.parse(json).WebUsbAllowDevicesForUrls, expected);
  assert.match(install.text, /30f1\|30f2/);
  assert.match(remove.text, /rm -f \/etc\/udev\/rules\.d\/60-slogic-webusb\.rules/);
  const mac = stationFiles('macos', ORIGIN).install.text;
  assert.match(mac, /<string>com\.google\.Chrome<\/string>/);
  assert.match(mac, /<string>https:\/\/ota\.example\.com<\/string>/);
});
