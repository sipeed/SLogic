// Demo mode (?demo, ?demo=16u3): a stand-in for navigator.usb with a simulated
// SLogic that switches modes and holds a simulated SPI flash, so the whole
// update can be tried and tested without hardware. Nothing here runs unless
// the page is opened with ?demo.

import { MODELS, VID } from './devices.js';
import { CMD_SET_REGISTER, CMD_READ_REGISTER, CMD_READ_DATA } from './spi.js';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let boardCount = 0;

class FlashSim {
  constructor() {
    this.uidSeed = ++boardCount; // each board has its own flash unique ID
    this.mem = new Uint8Array(1 << 24).fill(0xa5);
    this.wel = false;
    this.wip = 0;
    this.pending = new Uint8Array(0);
    this.next = new Uint8Array(0);
  }

  onWrite(pkt) {
    const dv = new DataView(pkt.buffer, pkt.byteOffset, pkt.byteLength);
    const cmd = dv.getUint32(0, true);
    const len = dv.getUint32(4, true);
    const data = pkt.subarray(8, 8 + len);
    if (cmd === CMD_SET_REGISTER) {
      const tc = new DataView(data.buffer, data.byteOffset).getUint32(8, true);
      const mode = (tc >>> 24) & 0xf;
      const wr = ((tc >>> 12) & 0x1ff) + 1;
      const rd = (tc & 0x1ff) + 1;
      const payload = data.subarray(40);
      this.pending = mode === 7 ? new Uint8Array(0)
        : this.spi(mode === 2 ? new Uint8Array(0) : payload.subarray(0, wr), [2, 3, 5].includes(mode) ? rd : 0);
    } else if (cmd === CMD_READ_DATA) {
      this.next = this.pending;
      this.pending = new Uint8Array(0);
    } else if (cmd === CMD_READ_REGISTER) {
      const regs = new Uint8Array(40);
      new DataView(regs.buffer).setUint32(28, 0x00404000, true);
      this.next = regs;
    }
  }

  onRead(n) {
    const out = this.next.slice(0, n);
    this.next = new Uint8Array(0);
    return out;
  }

  spi(wr, rd) {
    const op = wr[0];
    const addr = wr.length >= 4 ? (wr[1] << 16) | (wr[2] << 8) | wr[3] : 0;
    switch (op) {
      case 0x9f: return Uint8Array.of(0xef, 0x40, 0x18).subarray(0, rd);
      case 0x4b: return Uint8Array.from({ length: rd }, (_, i) => (i === 0 ? this.uidSeed : 0x10 + i));
      case 0x06: this.wel = true; break;
      case 0x04: this.wel = false; break;
      case 0xd8:
        if (this.wel) { this.mem.fill(0xff, addr & ~0xffff, (addr & ~0xffff) + 0x10000); this.wip = 3; this.wel = false; }
        break;
      case 0x02:
        if (this.wel) {
          wr.subarray(4).forEach((b, i) => { this.mem[(addr & ~0xff) | ((addr + i) & 0xff)] &= b; });
          this.wel = false;
        }
        break;
      case 0x05:
        if (this.wip) { this.wip--; return Uint8Array.of(0x03); }
        return Uint8Array.of(this.wel ? 0x02 : 0x00);
      case 0x0b: return this.mem.slice(addr, addr + rd);
    }
    return new Uint8Array(0);
  }
}

class DemoDevice {
  constructor(bus, board, mode, serial) {
    this.bus = bus;
    this.board = board;
    const model = board.model;
    this.model = model;
    this.mode = mode;
    this.vendorId = VID;
    this.productId = mode === 'app' ? model.appPid : model.dfuPid;
    this.productName = `${model.name}${mode === 'dfu' ? ' DFU' : ''}`;
    this.manufacturerName = 'Sipeed';
    this.serialNumber = serial;
    this.opened = false;
    this.configuration = null;
    this.ops = 0;
  }

  async open() {
    await sleep(20);
    if (this.gone) throw new DOMException('The device was disconnected.', 'NotFoundError');
    this.opened = true;
  }
  async close() { this.opened = false; }
  async selectConfiguration() {
    const ep = (direction) => ({ endpointNumber: 1, direction, type: 'bulk', packetSize: 512 });
    this.configuration = {
      configurationValue: 1,
      interfaces: [{ interfaceNumber: 0, alternate: { endpoints: [ep('out'), ep('in')] } }],
    };
  }
  async claimInterface() { if (!this.opened) throw new DOMException('not open', 'InvalidStateError'); }
  async releaseInterface() {}
  async reset() {}

  async yieldSometimes() {
    if (++this.ops % 400 === 0) await sleep(0);
  }

  /** Fault injection: board.failIn = n makes the n-th transfer from now fail. */
  fault() {
    // Like real WebUSB: a device that left the bus fails every transfer.
    if (this.gone) throw new DOMException('The device was disconnected.', 'NotFoundError');
    const b = this.board;
    if (b.failIn > 0 && --b.failIn === 0) {
      if (b.failRepeat) b.failIn = b.failRepeat;
      throw new DOMException('A transfer error has occurred.', 'NetworkError');
    }
  }

  async transferOut(_ep, data) {
    await this.yieldSometimes();
    this.fault();
    this.board.flash.onWrite(new Uint8Array(data.buffer ?? data, data.byteOffset ?? 0, data.byteLength));
    return { status: 'ok', bytesWritten: data.byteLength };
  }

  async transferIn(_ep, n) {
    await this.yieldSometimes();
    this.fault();
    const out = this.board.flash.onRead(n);
    return { status: 'ok', data: new DataView(out.buffer, out.byteOffset, out.byteLength) };
  }

  async controlTransferOut(setup) {
    if (setup.request === 0x30 && setup.index === 0x5253 && this.model.reconfig) {
      setTimeout(() => this.bus.replace(this, this.mode === 'app' ? 'dfu' : 'app'), 600);
      throw new DOMException('device gone', 'NetworkError');
    }
    return { status: 'ok' };
  }
}

/**
 * Minimal navigator.usb double. `permitAll` stands in for the browser policy
 * that pre-authorizes SLogic devices for a production station.
 */
class DemoUsb extends EventTarget {
  constructor(modelId, { mode = 'app', permitAll = false, boards = 1 } = {}) {
    super();
    this.permitAll = permitAll;
    this.permitted = new Set();
    this.devices = [];
    this.boards = [];
    for (let i = 0; i < boards; i++) this.plug(modelId, mode, true);
  }

  /** The simulated flash of the first board (single-device tests). */
  get flash() { return this.boards[0].flash; }

  /** Connect a new board. */
  plug(modelId, mode = 'dfu', quiet = false) {
    const board = { model: MODELS[modelId], flash: new FlashSim(), failIn: 0, failRepeat: 0 };
    this.boards.push(board);
    const d = new DemoDevice(this, board, mode, mode === 'app' ? '202610140927' : '');
    this.devices.push(d);
    if (!quiet && this.allowed(d)) this.dispatch('connect', d);
    return d;
  }

  /** The same board drops off the bus and comes back (flaky cable). */
  async reconnect(device, delayMs = 300) {
    this.unplug(device);
    await sleep(delayMs);
    const d = new DemoDevice(this, device.board, device.mode, device.serialNumber);
    this.devices.push(d);
    if (this.allowed(d)) this.dispatch('connect', d);
    return d;
  }

  unplug(device) {
    if (!this.devices.includes(device)) return;
    this.devices = this.devices.filter((d) => d !== device);
    device.gone = true;
    this.dispatch('disconnect', device);
  }

  allowed(d) { return this.permitAll || this.permitted.has(d.productId); }

  async getDevices() {
    return this.devices.filter((d) => this.allowed(d));
  }

  async requestDevice({ filters }) {
    await sleep(150);
    // A 16U3 has no RECONFIG: asking for its update-mode device stands in for
    // the user pressing MODE.
    const wantsDfu = filters.every((f) => Object.values(MODELS).some((m) => m.dfuPid === f.productId));
    const app = this.devices.find((d) => d.mode === 'app');
    if (wantsDfu && app && !app.model.reconfig) this.replace(app, 'dfu', true);
    const d = this.devices.find((x) => filters.some((f) => f.productId === x.productId));
    if (!d) throw new DOMException('No device selected.', 'NotFoundError');
    this.permitted.add(d.productId);
    return d;
  }

  replace(old, mode, quiet = false) {
    this.devices = this.devices.filter((d) => d !== old);
    old.gone = true;
    if (!quiet) this.dispatch('disconnect', old);
    const serial = mode === 'app' ? '202610150930' : '';
    const d = new DemoDevice(this, old.board, mode, serial);
    this.devices.push(d);
    // The update-mode device stays authorized only after the first chooser pick.
    if (this.allowed(d)) this.dispatch('connect', d);
  }

  dispatch(type, device) {
    const e = new Event(type);
    e.device = device;
    this.dispatchEvent(e);
  }
}

export function demoUsb(param, options) {
  return new DemoUsb(param === '16u3' ? 'slogic16u3' : 'slogic32u3', options);
}

/** A plausible demo image: 0xFF preamble, then pseudo-random bitstream bytes. */
export function demoFirmware(model) {
  const size = model.id === 'slogic16u3' ? 496484 : 1715588;
  const out = new Uint8Array(size);
  let x = 0x2468ace1;
  for (let i = 0; i < size; i++) {
    x = (Math.imul(x, 1103515245) + 12345) >>> 0;
    out[i] = i < 24 ? 0xff : (x >>> 16) & 0xff;
  }
  return new File([out], `${model.id}_demo.bin`);
}
