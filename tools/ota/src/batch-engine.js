// Batch update: flash every connected board of one model in parallel.
//
// The engine watches navigator.usb (connect/disconnect), so it relies on the
// boards being authorized without a click, e.g. through the browser policy
// WebUsbAllowDevicesForUrls on a production station; `add(device)` covers
// devices picked by hand.
//
// A board's life:  normal mode --RECONFIG--> update mode --flash--> RECONFIG
// --> normal mode (done: steady cyan LED) --unplug--> removed.
// WebUSB doesn't say which USB port a device is on, and the update-mode
// device has no serial number, so a board that re-enumerates is matched to
// the oldest board waiting for that transition. In update mode the engine also
// reads the flash chip's unique ID, which identifies the physical board: a
// board that drops off the bus and comes back (flaky cable, unplugged by
// mistake) keeps its row, its retry count, and is counted once.
//
// The page cannot change the LED. A board that failed stays in update mode
// (cyan + slow red blink) like the ones in progress, so failures are retried
// automatically while the board stays connected, and when nothing else is in
// progress every blinking board is a failed one.

import { identify } from './devices.js';
import { UsbLink, sendReconfig } from './usb.js';
import { SpiFlash, flashFirmware } from './flash.js';
import { probe } from './updater.js';

// switching:  RECONFIG sent, waiting for the update-mode device
// waiting:    normal mode, needs the MODE button (16U3) or the batch is idle
// ready:      update mode, batch not started
// flashing:   erase / write / verify running
// restarting: flashed, RECONFIG sent, waiting for the normal-mode device
// done:       flashed and verified (replug: 16U3 needs a replug to start it)
// retrying:   failed, about to try again (board still connected)
// failed / wrong-model / removed (message 'interrupted' if unplugged mid-update)
export const ACTIVE = new Set(['switching', 'flashing', 'restarting', 'retrying']);

const REENUM_TIMEOUT_MS = 20000;
const MAX_REMOVED_ROWS = 12;
export const MAX_ATTEMPTS = 3;
const RETRY_DELAY_MS = 1500;
const RECONNECT_WINDOW_MS = 5000; // a flicker takes 1-2 s

export class BatchEngine extends EventTarget {
  constructor({ usb, log = () => {} }) {
    super();
    this.usb = usb;
    this.log = log;
    this.boards = [];
    this.nextId = 1;
    this.running = false;
    this.model = null;
    this.firmware = null;
    // Off by default: factory boards arrive in update mode; a board in normal
    // mode on a production line is usually one that is already done.
    this.updateNormal = false;
    this.targetSerial = '';
    this.flashed = new Set(); // flash UIDs of boards written and verified this session
    this.onConnect = (e) => this.add(e.device);
    this.onDisconnect = (e) => this.removed(e.device);
  }

  /** Begin watching for devices (call once). */
  async attach() {
    this.usb.addEventListener('connect', this.onConnect);
    this.usb.addEventListener('disconnect', this.onDisconnect);
    for (const d of await this.usb.getDevices()) this.add(d);
  }

  detach() {
    this.usb.removeEventListener('connect', this.onConnect);
    this.usb.removeEventListener('disconnect', this.onDisconnect);
  }

  configure({ model, firmware, updateNormal = false }) {
    const changed = model !== this.model || firmware !== this.firmware;
    this.model = model;
    this.firmware = firmware;
    this.updateNormal = updateNormal;
    if (changed) this.targetSerial = '';
    for (const b of this.boards) if (b.state === 'wrong-model' || b.state === 'waiting' || b.state === 'ready') this.classify(b);
    this.changed();
  }

  start() {
    if (!this.model || !this.firmware) return;
    this.running = true;
    this.startedOnce = true;
    this.log(`Batch started: ${this.model.name}, ${this.firmware.length} bytes`);
    for (const b of this.boards) if (['waiting', 'ready'].includes(b.state)) this.classify(b);
    this.changed();
  }

  stop() {
    this.running = false;
    this.log('Batch paused: boards already in progress finish');
    this.changed();
  }

  counts() {
    const c = { done: 0, active: 0, failed: 0, waiting: 0 };
    for (const b of this.boards) {
      if (b.state === 'removed') continue;
      if (b.state === 'done') c.done++;
      else if (ACTIVE.has(b.state)) c.active++;
      else if (b.state === 'failed' || b.state === 'wrong-model') c.failed++;
      else c.waiting++;
    }
    c.total = this.flashed.size;
    return c;
  }

  /** Remove rows of boards that have been unplugged. */
  clearRemoved() {
    this.boards = this.boards.filter((b) => b.state !== 'removed');
    this.changed();
  }

  /* ---------------------------------------------------------------- devices */

  add(device) {
    const info = identify(device, this.model);
    if (!info || this.boards.some((b) => b.device === device && b.state !== 'removed')) return;

    // A board we are moving between modes, coming back in its new mode.
    // A restarted board that showed up late (already counted as done) still
    // has to be matched, or it would look like a new board to update.
    const waiting = (b) => (info.mode === 'dfu' ? b.state === 'switching'
      : b.state === 'restarting' || (b.state === 'done' && b.awaitingApp));
    const pending = this.boards
      .filter((b) => waiting(b) && (!this.model || b.model.id === info.model.id))
      .sort((a, b) => a.since - b.since)[0];
    if (pending) {
      clearTimeout(pending.timer);
      pending.device = device;
      pending.mode = info.mode;
      pending.serial = device.serialNumber || '';
      if (info.mode === 'app') this.finishRestart(pending);
      else this.flash(pending);
      return;
    }

    // A finished board that dropped off the bus and came back: same row.
    if (info.mode === 'app' && this.targetSerial && device.serialNumber === this.targetSerial) {
      const back = this.boards
        .filter((b) => b.state === 'removed' && b.wasDone && Date.now() - b.removedAt < RECONNECT_WINDOW_MS)
        .sort((a, b) => b.removedAt - a.removedAt)[0];
      if (back) {
        Object.assign(back, { device, mode: 'app', serial: device.serialNumber, wasDone: false });
        this.log(`Board #${back.id}: reconnected`);
        return this.set(back, 'done', back.message);
      }
    }

    const board = {
      id: this.nextId++, device, model: info.model, mode: info.mode,
      serial: device.serialNumber || '', state: 'new', phase: '', done: 0, total: 0,
      message: '', since: Date.now(), started: 0, finished: 0, timer: null,
      uid: '', attempts: 0, removedAt: 0,
    };
    this.boards.push(board);
    this.log(`Board #${board.id}: ${info.model.name}, ${info.mode === 'app' ? 'normal' : 'update'} mode${board.serial ? `, S/N ${board.serial}` : ''}`);
    this.classify(board);
  }

  removed(device) {
    const b = this.boards.find((x) => x.device === device && x.state !== 'removed');
    if (!b) return;
    // Leaving the bus is part of switching modes.
    if (b.state === 'switching' || b.state === 'restarting') return;
    clearTimeout(b.timer);
    b.removedAt = Date.now();
    if (b.state === 'flashing' || b.state === 'retrying') {
      // Plugged back in, it is recognized by its flash ID and continues here.
      b.wasDone = false;
      this.set(b, 'removed', 'interrupted');
      this.log(`Board #${b.id}: unplugged during the update`);
    } else {
      b.wasDone = b.state === 'done';
      this.set(b, 'removed', b.state === 'failed' ? 'failed' : '');
      this.log(`Board #${b.id}: unplugged`);
    }
    // Keep the most recent unplugged rows only.
    const gone = this.boards.filter((x) => x.state === 'removed');
    if (gone.length > MAX_REMOVED_ROWS) {
      const drop = new Set(gone.slice(0, gone.length - MAX_REMOVED_ROWS));
      this.boards = this.boards.filter((x) => !drop.has(x));
    }
    this.changed();
  }

  /** Decide what to do with a board that is idle in some mode. */
  classify(b) {
    if (this.model && b.model.id !== this.model.id) {
      return this.set(b, 'wrong-model');
    }
    if (b.mode === 'app') {
      if (this.targetSerial && b.serial === this.targetSerial) {
        return this.set(b, 'done', 'already');
      }
      if (this.running && this.updateNormal && b.model.reconfig) return this.switchToDfu(b);
      return this.set(b, 'waiting', b.model.reconfig ? '' : 'press-mode');
    }
    if (this.running && this.firmware) return this.flash(b);
    return this.set(b, 'ready');
  }

  /* ---------------------------------------------------------------- steps */

  async switchToDfu(b) {
    this.set(b, 'switching');
    b.since = Date.now();
    this.log(`Board #${b.id}: switching to update mode`);
    try {
      await sendReconfig(b.device);
    } catch (e) {
      return this.fail(b, e.code === 'busy' ? 'busy' : e.message);
    }
    b.timer = setTimeout(() => {
      if (b.state === 'switching') this.fail(b, 'no-dfu');
    }, REENUM_TIMEOUT_MS);
  }

  async flash(b) {
    if (!this.firmware || !this.model) return this.set(b, 'ready');
    const model = { ...this.model, ...(b.model.writeChunk < this.model.writeChunk ? { writeChunk: b.model.writeChunk } : {}) };
    const firmware = this.firmware;
    this.set(b, 'flashing');
    b.started = Date.now();
    b.phase = 'check';
    b.done = 0;
    b.total = 1;
    this.log(`Board #${b.id}: writing ${firmware.length} bytes`);
    let link;
    b.attempts++;
    // This attempt owns the row only while the row still points at this
    // device and run: a board that was unplugged and came back is driven by a
    // newer attempt, and the old one must not touch the row any more.
    const device = b.device;
    const run = (b.run = (b.run ?? 0) + 1);
    const mine = () => b.device === device && b.run === run;
    try {
      link = await new UsbLink(device).open();
      if (!(await probe(link, model))) throw Object.assign(new Error('no answer from the update-mode device'), { code: 'no-bridge' });
      const flash = new SpiFlash(link, { writeChunk: model.writeChunk, readChunk: model.readChunk });
      const uid = Array.from(await flash.readUid(), (x) => x.toString(16).padStart(2, '0')).join('');
      b = this.adopt(b, uid);
      b.run = run;
      if (this.flashed.has(uid) && b.firmware === firmware) {
        // Written and verified earlier this session; it just reconnected.
        b.attempts = 0;
        await link.close();
        this.log(`Board #${b.id}: reconnected, already written`);
        return this.afterWrite(b);
      }
      let last = 0;
      await flashFirmware(flash, {
        addr: model.flashAddr, firmware, verify: true,
        report: ({ phase, done, total }) => {
          if (!mine()) return;
          b.phase = phase;
          b.done = done;
          b.total = total;
          const now = Date.now();
          if (now - last > 150 || done === total) { last = now; this.changed(); }
        },
      });
    } catch (e) {
      await link?.close();
      if (!mine() || b.state === 'removed') return;
      return this.fail(b, typeof e.code === 'string' ? `[${e.code}] ${e.message}` : e.message);
    }
    await link.close();
    if (!mine() || b.state === 'removed') return;
    b.finished = Date.now();
    b.firmware = firmware;
    this.flashed.add(b.uid || `row-${b.id}`);
    b.attempts = 0;
    this.log(`Board #${b.id}: verified in ${((b.finished - b.started) / 1000).toFixed(1)} s`);
    return this.afterWrite(b);
  }

  /**
   * The row for the board with this flash ID: an earlier row of the same
   * board (it dropped off the bus and came back) takes over the device.
   */
  adopt(b, uid) {
    const earlier = this.boards.find((x) => x !== b && x.uid === uid);
    if (!earlier) {
      b.uid = uid;
      return b;
    }
    // An attempt cut short by unplugging is redone without counting it.
    Object.assign(earlier, {
      device: b.device, mode: b.mode, serial: b.serial, attempts: Math.max(earlier.attempts, 1),
      state: b.state, phase: b.phase, done: b.done, total: b.total, started: b.started, message: '',
    });
    this.boards = this.boards.filter((x) => x !== b);
    this.log(`Board #${earlier.id}: reconnected (same flash ID)`);
    this.changed();
    return earlier;
  }

  /** Written and verified: restart into the application, or ask for a replug. */
  async afterWrite(b) {
    if (!b.model.reconfig) {
      return this.set(b, 'done', 'replug');
    }
    this.set(b, 'restarting');
    b.since = Date.now();
    try { await sendReconfig(b.device); } catch { /* it restarts anyway */ }
    // Without a policy the restarted board may not be visible; it is verified,
    // so count it as done.
    b.timer = setTimeout(() => {
      if (b.state === 'restarting') {
        b.awaitingApp = true;
        this.set(b, 'done', 'restarted-unseen');
      }
    }, REENUM_TIMEOUT_MS);
  }

  finishRestart(b) {
    b.awaitingApp = false;
    if (!this.targetSerial && b.serial) {
      this.targetSerial = b.serial;
      this.log(`New firmware S/N: ${b.serial}`);
    }
    this.log(`Board #${b.id}: done`);
    this.set(b, 'done');
  }

  fail(b, message) {
    clearTimeout(b.timer);
    // Still connected in update mode: try again on its own.
    if (b.mode === 'dfu' && b.attempts > 0 && b.attempts < MAX_ATTEMPTS && this.firmware) {
      this.log(`Board #${b.id}: attempt ${b.attempts} failed (${message}); retrying`);
      this.set(b, 'retrying', message);
      b.timer = setTimeout(() => { if (b.state === 'retrying') this.flash(b); }, RETRY_DELAY_MS);
      return;
    }
    this.log(`Board #${b.id}: failed: ${message}`);
    this.set(b, 'failed', message);
  }

  /** Retry a failed board that is still connected. */
  retry(b) {
    if (b.state !== 'failed') return;
    b.message = '';
    b.attempts = 0;
    if (b.mode === 'dfu') this.flash(b);
    else this.classify(b);
  }

  set(b, state, message = '') {
    b.state = state;
    b.message = message;
    this.changed();
  }

  changed() {
    this.dispatchEvent(new Event('change'));
  }
}
