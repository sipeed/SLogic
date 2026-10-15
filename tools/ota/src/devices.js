// SLogic models, their USB IDs in application (APP) and update (DFU) mode,
// and the update parameters proven on the production flasher
// (SLogic production-test tools, resources/products/*/product.toml [ota]).

export const VID = 0x359f;

export const MODELS = {
  slogic16u3: {
    id: 'slogic16u3',
    name: 'SLogic16U3',
    appPid: 0x3031,
    dfuPid: 0x30f1,
    // No USB RECONFIG request: the user switches modes on the device.
    reconfig: false,
    flashAddr: 0x0,
    writeChunk: 12, // the 16U3 bridge FIFO fails at 16
    readChunk: 64,
    // Typical image sizes, only for a "wrong model?" warning.
    typicalSize: [0x40000, 0x100000],
  },
  slogic32u3: {
    id: 'slogic32u3',
    name: 'SLogic32U3',
    appPid: 0x3032,
    dfuPid: 0x30f2,
    reconfig: true,
    flashAddr: 0x0,
    writeChunk: 48,
    readChunk: 64,
    typicalSize: [0x100000, 0x400000],
  },
};

export const USB_FILTERS = Object.values(MODELS).flatMap((m) => [
  { vendorId: VID, productId: m.appPid },
  { vendorId: VID, productId: m.dfuPid },
]);

export const DFU_FILTERS = Object.values(MODELS).map((m) => ({ vendorId: VID, productId: m.dfuPid }));

/**
 * Model and mode of a USB device, or null if it isn't an SLogic.
 * `hint` is the model last seen in APP mode: early SLogic32U3 update firmware
 * shared the 16U3 DFU ID 0x30F1, so a 0x30F1 device that we just switched from
 * a 32U3 is still a 32U3 (flashed with the conservative 16U3 chunk size).
 */
export function identify(device, hint) {
  if (device.vendorId !== VID) return null;
  for (const m of Object.values(MODELS)) {
    if (device.productId === m.appPid) return { model: m, mode: 'app' };
    if (device.productId === m.dfuPid) {
      if (hint && hint.id === 'slogic32u3' && m.id === 'slogic16u3') {
        return { model: { ...hint, writeChunk: MODELS.slogic16u3.writeChunk }, mode: 'dfu' };
      }
      return { model: m, mode: 'dfu' };
    }
  }
  return null;
}

/** Sanity checks on a firmware image; returns warning codes (never blocks). */
export function inspectFirmware(bytes, fileName, model) {
  const warnings = [];
  const head = bytes.subarray(0, 16);
  if (bytes.length < 0x400 || !head.every((b) => b === 0xff)) warnings.push('not-bitstream');
  if (model) {
    const [lo, hi] = model.typicalSize;
    if (bytes.length < lo || bytes.length > hi) warnings.push('size-unusual');
    const name = fileName.toLowerCase().replace(/[^a-z0-9]/g, '');
    const other = Object.values(MODELS).find((m) => m.id !== model.id && name.includes(m.id.replace('slogic', '')));
    if (other && !name.includes(model.id.replace('slogic', ''))) warnings.push('name-other-model');
  }
  return warnings;
}
