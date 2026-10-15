// The one-click update: APP -> DFU switch, flash, DFU -> APP restart.
//
// WebUSB only lets a page open devices the user has picked in the browser's
// chooser. A device that re-enumerates with another product ID (APP <-> DFU)
// is a new device to the browser, so when it isn't already authorized the
// update pauses and asks the UI for one click (`gesture`), then continues.

import { DFU_FILTERS, identify } from './devices.js';
import { UsbLink, sendReconfig } from './usb.js';
import { SpiFlash, flashFirmware, FlashError } from './flash.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Poll the authorized devices until `match` finds one. Gives up after
 * `timeoutMs`, or `graceMs` after `old` (the device that is re-enumerating)
 * has left the bus: an unauthorized new device never shows up here, so there
 * is no point in waiting longer before asking the user.
 */
export async function waitForDevice(usb, match, timeoutMs, signal, { old, graceMs = 2500 } = {}) {
  const end = Date.now() + timeoutMs;
  let goneAt = 0;
  for (;;) {
    const devices = await usb.getDevices();
    const found = devices.find(match);
    if (found) return found;
    if (old && !goneAt && !devices.includes(old)) goneAt = Date.now();
    if (Date.now() > end || signal?.aborted) return null;
    if (goneAt && Date.now() - goneAt > graceMs) return null;
    await sleep(300);
  }
}

/**
 * @param usb       navigator.usb (or the demo double)
 * @param device    the selected USBDevice (APP or DFU mode)
 * @param model     MODELS entry for it
 * @param firmware  Uint8Array
 * @param on        { step(id, state), progress({phase, done, total}), log(msg),
 *                    gesture(kind) -> Promise<USBDevice>, device(USBDevice) }
 * @returns { restarted: boolean, appDevice?: USBDevice }
 */
export async function runUpdate({ usb, device, model, firmware, on, signal }) {
  let info = identify(device, model);
  let dfu = device;

  // 1. Enter update (DFU) mode.
  if (info.mode === 'app') {
    on.step('switch', 'active');
    if (model.reconfig) {
      on.log(`Sending RECONFIG to ${model.name} (APP mode)`);
      await sendReconfig(device);
      dfu = await waitForDevice(usb, (d) => identify(d, model)?.mode === 'dfu', 15000, signal,
        { old: device });
      if (!dfu) {
        on.log('Update-mode device is not authorized yet; asking the user');
        dfu = await on.gesture('authorize-dfu');
      }
    } else {
      dfu = await on.gesture('manual-dfu');
    }
    info = identify(dfu, model);
    if (!info || info.mode !== 'dfu') throw new FlashError('not-dfu', 'Selected device is not in update mode');
    on.device?.(dfu);
    on.log(`Update mode: ${info.model.name} (USB ${hex4(dfu.vendorId)}:${hex4(dfu.productId)})`);
  }
  on.step('switch', 'done');
  const target = info.model;

  // 2. Open the bridge; recover a bridge left stuck by an interrupted session.
  on.step('flash', 'active');
  let link = await openHealthy(usb, dfu, target, on, signal);

  // 3. Flash.
  try {
    const flash = new SpiFlash(link, {
      writeChunk: target.writeChunk, readChunk: target.readChunk, signal,
    });
    const result = await flashFirmware(flash, {
      addr: target.flashAddr, firmware, verify: true,
      report: (r) => on.progress(r),
    });
    on.log(`Flash ID ${result.id}, UID ${result.uid}`);
  } finally {
    await link.close();
  }
  on.step('flash', 'done');

  // 4. Back to the application.
  on.step('restart', 'active');
  if (!target.reconfig) {
    on.step('restart', 'manual');
    return { restarted: false };
  }
  on.log('Sending RECONFIG to restart into the application');
  await sendReconfig(dfu);
  const app = await waitForDevice(usb, (d) => identify(d, target)?.mode === 'app', 15000, signal,
    { old: dfu, graceMs: 4000 });
  on.step('restart', 'done');
  if (app) on.device?.(app);
  return { restarted: true, appDevice: app ?? undefined };
}

async function openHealthy(usb, dfu, model, on, signal) {
  let link = await new UsbLink(dfu).open();
  if (await probe(link, model)) return link;

  on.log('Bridge did not answer; resetting the USB device');
  await link.close();
  try {
    await dfu.open();
    await dfu.reset();
  } catch { /* the device may already be re-enumerating */ }
  try { await dfu.close(); } catch { /* gone */ }
  await sleep(2000);
  let again = await waitForDevice(usb, (d) => d.productId === dfu.productId, 5000, signal);
  if (!again) again = await on.gesture('replug-dfu');
  on.device?.(again);
  link = await new UsbLink(again).open();
  if (await probe(link, model)) return link;
  await link.close();
  throw new FlashError('no-bridge', 'The update-mode device does not respond');
}

/** Bridge reset + flash ID read with short timeouts. */
export async function probe(link, model) {
  const saved = link.timeoutMs;
  link.timeoutMs = 800;
  try {
    const flash = new SpiFlash(link, { writeChunk: model.writeChunk, readChunk: model.readChunk });
    await flash.reset();
    await flash.readId();
    return true;
  } catch {
    return false;
  } finally {
    link.timeoutMs = saved;
  }
}

export const hex4 = (n) => n.toString(16).padStart(4, '0');

export { DFU_FILTERS };
