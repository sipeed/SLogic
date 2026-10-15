// WebUSB transport for the DFU bulk endpoints, plus the RECONFIG request that
// makes an SLogic32U3 re-enumerate in the other mode.

export class TransportError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}

function withTimeout(promise, ms, what) {
  let timer;
  return Promise.race([
    promise.finally(() => clearTimeout(timer)),
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new TransportError('timeout', `${what} timed out`)), ms);
    }),
  ]);
}

/** Bulk link over interface 0 of an opened DFU device. */
export class UsbLink {
  constructor(device, { timeoutMs = 1000 } = {}) {
    this.device = device;
    this.timeoutMs = timeoutMs;
  }

  async open() {
    const d = this.device;
    try {
      if (!d.opened) await d.open();
      if (!d.configuration) await d.selectConfiguration(1);
      await d.claimInterface(0);
    } catch (e) {
      throw new TransportError('open', e.message);
    }
    const alt = d.configuration.interfaces.find((i) => i.interfaceNumber === 0).alternate;
    this.epOut = alt.endpoints.find((e) => e.direction === 'out' && e.type === 'bulk');
    this.epIn = alt.endpoints.find((e) => e.direction === 'in' && e.type === 'bulk');
    if (!this.epOut || !this.epIn) throw new TransportError('endpoints', 'bulk endpoints not found');
    return this;
  }

  async write(data) {
    const r = await withTimeout(this.device.transferOut(this.epOut.endpointNumber, data),
      this.timeoutMs, 'USB write');
    if (r.status !== 'ok') throw new TransportError('usb', `USB write ${r.status}`);
    return r.bytesWritten;
  }

  /**
   * Read up to n bytes. The request is rounded up to whole packets: asking for
   * less than a packet makes a full packet from the device an overflow.
   */
  async read(n) {
    const mps = this.epIn.packetSize || 64;
    const r = await withTimeout(this.device.transferIn(this.epIn.endpointNumber, Math.ceil(n / mps) * mps),
      this.timeoutMs, 'USB read');
    if (r.status !== 'ok') throw new TransportError('usb', `USB read ${r.status}`);
    const v = r.data;
    return new Uint8Array(v.buffer, v.byteOffset, Math.min(n, v.byteLength)).slice();
  }

  async close() {
    try { await this.device.releaseInterface(0); } catch { /* already gone */ }
    try { await this.device.close(); } catch { /* already gone */ }
  }
}

/**
 * Ask the device to reconfigure its FPGA and re-enumerate in the other mode
 * (SLogic32U3, APP <-> DFU). The device usually drops off the bus before the
 * status stage, so a failed transfer still counts as sent; success is the new
 * device appearing.
 */
export async function sendReconfig(device) {
  try {
    if (!device.opened) await device.open();
    if (!device.configuration) await device.selectConfiguration(1);
  } catch (e) {
    throw new TransportError('busy', e.message);
  }
  try { await device.claimInterface(0); } catch { /* not needed on every OS */ }
  try {
    await withTimeout(device.controlTransferOut({
      requestType: 'vendor', recipient: 'device', request: 0x30, value: 0x0001, index: 0x5253,
    }), 2000, 'RECONFIG');
  } catch { /* expected: the device left mid-transfer */ }
  try { await device.close(); } catch { /* gone */ }
}

export const webUsbAvailable = () => typeof navigator !== 'undefined' && 'usb' in navigator;
