// The device status LED as the page draws it: steady cyan in normal (APP)
// mode, cyan with a slow red blink in update (DFU) mode.

export function ledIcon(mode) {
  const led = document.createElement('span');
  led.className = `led ${mode}`;
  led.setAttribute('aria-hidden', 'true');
  led.append(document.createElement('i'));
  if (mode === 'dfu') led.append(document.createElement('i'));
  return led;
}
