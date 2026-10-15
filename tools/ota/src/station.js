// Production-station setup for the batch page: install files for the browser
// policy WebUsbAllowDevicesForUrls, which lets this page open SLogic devices
// without a permission click per board (the update-mode device has no serial
// number, so the browser cannot remember a permission for it).
//
// A web page cannot change system settings, so these are files the operator
// runs once: a .reg file (Windows), a shell script (Linux, also installs the
// udev rule), a configuration profile (macOS). Chrome and Edge are covered;
// Chromium and Brave too on Linux.

import { MODELS, VID } from './devices.js';

const NAME = 'slogic-webusb';

// The site the update pages are published on. The policy allows this origin
// (every path on it), whichever address the page happens to be opened from.
export const STATION_ORIGIN = 'https://slogic.sipeed.com';
const UDEV_RULE = 'SUBSYSTEM=="usb", ATTRS{idVendor}=="359f", ATTRS{idProduct}=="0300|3031|3032|30f1|30f2", MODE="0666", TAG+="uaccess"';

export function policyValue(origin) {
  const devices = Object.values(MODELS).flatMap((m) => [m.appPid, m.dfuPid])
    .map((pid) => ({ vendor_id: VID, product_id: pid }));
  return [{ devices, urls: [origin] }];
}

export function detectOs() {
  const p = (navigator.userAgentData?.platform || navigator.platform || navigator.userAgent || '').toLowerCase();
  if (p.includes('win')) return 'windows';
  if (p.includes('mac')) return 'macos';
  return 'linux';
}

const crlf = (lines) => lines.join('\r\n') + '\r\n';
const regString = (s) => s.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
const REG_KEYS = ['HKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\Google\\Chrome',
  'HKEY_LOCAL_MACHINE\\SOFTWARE\\Policies\\Microsoft\\Edge'];

/** Windows: double-click to import (asks for administrator approval). */
function windowsFiles(origin) {
  const value = regString(JSON.stringify(policyValue(origin)));
  return {
    install: {
      name: `${NAME}-install.reg`, type: 'text/plain',
      text: crlf(['Windows Registry Editor Version 5.00', '',
        `; Lets ${origin} access SLogic analyzers over WebUSB without asking (Chrome, Edge).`,
        ...REG_KEYS.flatMap((k) => ['', `[${k}]`, `"WebUsbAllowDevicesForUrls"="${value}"`])]),
    },
    remove: {
      name: `${NAME}-remove.reg`, type: 'text/plain',
      text: crlf(['Windows Registry Editor Version 5.00', '',
        '; Removes the SLogic WebUSB policy (Chrome, Edge).',
        ...REG_KEYS.flatMap((k) => ['', `[${k}]`, '"WebUsbAllowDevicesForUrls"=-'])]),
    },
  };
}

const LINUX_DIRS = [
  ['google-chrome google-chrome-stable', '/etc/opt/chrome/policies/managed'],
  ['chromium chromium-browser', '/etc/chromium/policies/managed'],
  ['microsoft-edge microsoft-edge-stable', '/etc/opt/edge/policies/managed'],
  ['brave brave-browser', '/etc/brave/policies/managed'],
];

/** Linux: sudo sh <file>. Installs the policy for each browser found plus a udev rule. */
function linuxFiles(origin) {
  const json = JSON.stringify({ WebUsbAllowDevicesForUrls: policyValue(origin) }, null, 2);
  const head = ['#!/bin/sh', 'set -e',
    '[ "$(id -u)" = 0 ] || { echo "Run as root: sudo sh $0"; exit 1; }', ''];
  const has = (cmds) => cmds.split(' ').map((c) => `command -v ${c} >/dev/null 2>&1`).join(' || ');
  const install = [...head,
    `# Lets ${origin} access SLogic analyzers over WebUSB without asking.`,
    'found=0'];
  for (const [cmds, dir] of LINUX_DIRS) {
    install.push(`if ${has(cmds)}; then`,
      `  mkdir -p ${dir}`,
      `  cat > ${dir}/${NAME}.json <<'EOF'`, json, 'EOF',
      `  echo "policy installed: ${dir}/${NAME}.json"; found=1`, 'fi');
  }
  install.push('[ "$found" = 1 ] || echo "No Chrome, Chromium, Edge or Brave found; nothing installed for a browser."',
    `echo '${UDEV_RULE}' > /etc/udev/rules.d/60-${NAME}.rules`,
    'udevadm control --reload-rules && udevadm trigger || true',
    `echo "udev rule installed: /etc/udev/rules.d/60-${NAME}.rules"`,
    'echo "Restart the browser, then check chrome://policy (Edge: edge://policy)."', '');
  const remove = [...head, '# Removes the SLogic WebUSB policy and udev rule.'];
  for (const [, dir] of LINUX_DIRS) remove.push(`rm -f ${dir}/${NAME}.json`);
  remove.push(`rm -f /etc/udev/rules.d/60-${NAME}.rules`,
    'udevadm control --reload-rules || true',
    'echo "Removed. Restart the browser."', '');
  return {
    install: { name: `${NAME}-install.sh`, type: 'text/x-shellscript', text: install.join('\n') },
    remove: { name: `${NAME}-remove.sh`, type: 'text/x-shellscript', text: remove.join('\n') },
  };
}

const xml = (s) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

function plistValue(v, indent) {
  const pad = '  '.repeat(indent);
  if (Array.isArray(v)) return `${pad}<array>\n${v.map((x) => plistValue(x, indent + 1)).join('\n')}\n${pad}</array>`;
  if (typeof v === 'number') return `${pad}<integer>${v}</integer>`;
  if (typeof v === 'string') return `${pad}<string>${xml(v)}</string>`;
  return `${pad}<dict>\n${Object.entries(v).map(([k, x]) =>
    `${pad}  <key>${xml(k)}</key>\n${plistValue(x, indent + 1)}`).join('\n')}\n${pad}</dict>`;
}

/** Deterministic UUID-shaped id from text, so re-downloads replace the same profile. */
function stableUuid(text) {
  let h = 0x811c9dc5;
  const out = [];
  for (let round = 0; round < 4; round++) {
    for (const c of text + round) h = Math.imul(h ^ c.charCodeAt(0), 0x01000193) >>> 0;
    out.push(h.toString(16).padStart(8, '0'));
  }
  const s = out.join('').toUpperCase();
  return `${s.slice(0, 8)}-${s.slice(8, 12)}-4${s.slice(13, 16)}-8${s.slice(17, 20)}-${s.slice(20, 32)}`;
}

/** macOS: open the profile, then approve it in System Settings > Profiles. */
function macosFiles(origin) {
  const payload = (type, browser) => ({
    PayloadType: type,
    PayloadIdentifier: `com.sipeed.slogic.webusb.${browser}`,
    PayloadUUID: stableUuid(`${origin}/${browser}`),
    PayloadVersion: 1,
    PayloadDisplayName: `SLogic WebUSB (${browser})`,
    WebUsbAllowDevicesForUrls: policyValue(origin),
  });
  const profile = {
    PayloadType: 'Configuration',
    PayloadIdentifier: 'com.sipeed.slogic.webusb',
    PayloadUUID: stableUuid(origin),
    PayloadVersion: 1,
    PayloadDisplayName: 'SLogic WebUSB access',
    PayloadDescription: `Lets ${origin} access SLogic analyzers over WebUSB without asking (Chrome, Edge).`,
    PayloadScope: 'System',
    PayloadContent: [payload('com.google.Chrome', 'chrome'), payload('com.microsoft.Edge', 'edge')],
  };
  const text = ['<?xml version="1.0" encoding="UTF-8"?>',
    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
    '<plist version="1.0">', plistValue(profile, 0), '</plist>', ''].join('\n');
  return {
    install: { name: `${NAME}.mobileconfig`, type: 'application/x-apple-aspen-config', text },
    remove: null, // removed in System Settings > Privacy & Security > Profiles
  };
}

export function stationFiles(os, origin) {
  return { windows: windowsFiles, linux: linuxFiles, macos: macosFiles }[os](origin);
}

export function download({ name, type, text }) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
