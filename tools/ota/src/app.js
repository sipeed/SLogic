// Page controller: device selection, firmware file, the update run.

import { USB_FILTERS, DFU_FILTERS, identify, inspectFirmware } from './devices.js';
import { runUpdate, hex4 } from './updater.js';
import { AbortedError } from './flash.js';
import { webUsbAvailable } from './usb.js';
import { initLang, getLang, setLang, t } from './i18n.js';
import { ledIcon } from './led.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const DEMO = params.has('demo');

const WIKI = {
  en: 'https://wiki.sipeed.com/hardware/en/logic_analyzer/slogic32u3/Hardware_Specification.html#Firmware-Update',
  zh: 'https://wiki.sipeed.com/hardware/zh/logic_analyzer/slogic32u3/Hardware_Specification.html#%E6%9B%B4%E6%96%B0%E5%9B%BA%E4%BB%B6',
};

const STEPS = ['switch', 'check', 'erase', 'blank', 'program', 'verify', 'restart'];
const STEP_LABEL = { switch: 'sSwitch', check: 'sCheck', erase: 'sErase', blank: 'sBlank',
  program: 'sProgram', verify: 'sVerify', restart: 'sRestart' };

const state = {
  usb: null,
  device: null,     // selected USBDevice
  info: null,       // { model, mode }
  lastModel: null,  // model seen in APP mode (identifies an old 0x30F1 32U3)
  file: null,       // { name, bytes, sha, warnings }
  busy: false,
  abort: null,
  gesture: null,    // { kind, resolve, reject }
  stepState: {},
  result: null,     // { ok, title, body, button, action }
  deviceError: '',
};

/* ------------------------------------------------------------------ prefs */

function pref(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(`slogic-ota-${key}`);
    localStorage.setItem(`slogic-ota-${key}`, value);
  } catch { /* storage unavailable: preferences just don't persist */ }
  return null;
}

function currentTheme() {
  const set = document.documentElement.dataset.theme;
  if (set) return set;
  return matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

/* ------------------------------------------------------------------ render */

function applyStrings() {
  document.documentElement.lang = getLang() === 'zh' ? 'zh-CN' : 'en';
  document.title = t('title');
  for (const el of document.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll('[data-i18n-title]')) {
    el.title = t(el.dataset.i18nTitle);
    el.setAttribute('aria-label', el.title);
  }
  $('lang').textContent = t('langToggle');
  $('wiki').href = WIKI[getLang()];
  $('udev-cmd').textContent = UDEV_CMD;
  render();
}

const UDEV_CMD = [
  "sudo tee /etc/udev/rules.d/60-slogic.rules >/dev/null <<'END'",
  'SUBSYSTEM=="usb", ATTRS{idVendor}=="359f", ATTRS{idProduct}=="0300|3031|3032|30f1|30f2", MODE="0666", TAG+="uaccess"',
  'END',
  'sudo udevadm control --reload-rules && sudo udevadm trigger',
].join('\n');

function render() {
  // Banner
  const banner = $('banner');
  banner.classList.remove('info');
  if (!window.isSecureContext && !DEMO) {
    showBanner(t('insecureTitle'), t('insecureBody'));
  } else if (!state.usb) {
    showBanner(t('noWebUsbTitle'), t('noWebUsbBody'));
  } else if (DEMO) {
    showBanner(t('demoBanner'), '');
    banner.classList.add('info');
  } else {
    banner.hidden = true;
  }

  // Device
  const { device, info } = state;
  $('device-empty').hidden = !!device;
  $('device-info').hidden = !device;
  $('connect').disabled = !state.usb || state.busy;
  $('change').disabled = state.busy;
  if (device && info) {
    $('device-name').textContent = info.model.name;
    const pill = $('device-mode');
    pill.replaceChildren(ledIcon(info.mode), info.mode === 'app' ? t('modeApp') : t('modeDfu'));
    pill.className = `pill ${info.mode}`;
    $('device-led').replaceChildren(ledIcon(info.mode), info.mode === 'app' ? t('ledLegendApp') : t('ledLegendDfu'));
    $('device-serial-row').hidden = !device.serialNumber || info.mode !== 'app';
    $('device-serial').textContent = device.serialNumber || '';
    $('device-usb').textContent = `${hex4(device.vendorId)}:${hex4(device.productId)}`;
    const note = info.mode === 'app' && !info.model.reconfig ? t('manualDfuNote16') : '';
    $('device-note').hidden = !note;
    $('device-note').textContent = note;
  }
  $('device-error').hidden = !state.deviceError;
  $('device-error').textContent = state.deviceError;

  // Firmware
  const f = state.file;
  $('drop').hidden = !!f;
  $('file-info').hidden = !f;
  $('file-change').disabled = state.busy;
  if (f) {
    $('file-name').textContent = f.name;
    $('file-size').textContent = `${formatBytes(f.bytes.length)} (${f.bytes.length.toLocaleString()} B)`;
    $('file-hash').textContent = f.sha || '…';
    const warnings = info ? inspectFirmware(f.bytes, f.name, info.model) : inspectFirmware(f.bytes, f.name);
    f.warnings = warnings;
    const list = $('file-warnings');
    list.hidden = warnings.length === 0;
    list.replaceChildren(...warnings.map((w) => {
      const li = document.createElement('li');
      li.textContent = t({ 'not-bitstream': 'warnNotBitstream', 'size-unusual': 'warnSize',
        'name-other-model': 'warnName' }[w], { model: info?.model.name ?? 'SLogic' });
      return li;
    }));
    $('ack-row').hidden = warnings.length === 0;
    $('ack-text').textContent = t('ackWarnings', { model: info?.model.name ?? 'SLogic' });
    $('ack').disabled = state.busy;
  }

  // Update
  let ready = '';
  let canStart = false;
  if (!device) ready = t('readyNeedDevice');
  else if (!f) ready = t('readyNeedFile');
  else if (f.warnings.length && !$('ack').checked) ready = t('readyAck');
  else { ready = t('ready', { model: info.model.name, file: f.name }); canStart = true; }
  $('ready').textContent = ready;
  $('ready').hidden = state.busy || !!state.result;
  $('start').hidden = state.busy || !!state.result;
  $('start').disabled = !canStart || !state.usb;
  $('cancel').hidden = !state.busy;
  $('keep').hidden = !state.busy;

  const showSteps = state.busy || !!state.result;
  $('steps').hidden = !showSteps;
  if (showSteps) {
    $('steps').replaceChildren(...STEPS.map((id) => {
      const li = document.createElement('li');
      li.textContent = t(STEP_LABEL[id]);
      const s = state.stepState[id];
      if (s) li.className = s;
      return li;
    }));
  }

  const g = state.gesture;
  $('gesture').hidden = !g;
  if (g) {
    const m = (state.info?.model ?? state.lastModel)?.name ?? 'SLogic';
    const [title, body] = {
      'authorize-dfu': ['gAuthorizeTitle', 'gAuthorizeBody'],
      'manual-dfu': ['gManualTitle', 'gManualBody'],
      'replug-dfu': ['gReplugTitle', 'gReplugBody'],
    }[g.kind];
    $('gesture-title').textContent = t(title, { model: m });
    $('gesture-body').textContent = t(body, { model: m });
  }

  const r = state.result;
  $('result').hidden = !r;
  if (r) {
    $('result').className = `result ${r.ok ? 'ok' : 'fail'}`;
    $('result-title').textContent = r.title;
    $('result-body').textContent = r.body;
    $('result-btn').textContent = r.button;
  }
}

function showBanner(title, body) {
  $('banner').hidden = false;
  $('banner-title').textContent = title;
  $('banner-body').textContent = body;
}

function formatBytes(n) {
  if (n >= 1048576) return `${(n / 1048576).toFixed(2)} MiB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KiB`;
  return `${n} B`;
}

function formatTime(s) {
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60);
  return m ? `${m}:${String(s % 60).padStart(2, '0')}` : `${s}s`;
}

/* ------------------------------------------------------------------ log */

const logLines = [];
function log(msg) {
  const ts = new Date().toLocaleTimeString([], { hour12: false });
  logLines.push(`[${ts}] ${msg}`);
  $('log').textContent = logLines.join('\n');
  $('log').scrollTop = $('log').scrollHeight;
  $('log-box').hidden = false;
}

/* ------------------------------------------------------------------ device */

function selectDevice(device) {
  const info = device ? identify(device, state.lastModel) : null;
  state.device = info ? device : null;
  state.info = info;
  state.deviceError = '';
  if (info?.mode === 'app') state.lastModel = info.model;
  if (info) log(`Device: ${info.model.name}, ${info.mode.toUpperCase()} mode, USB ${hex4(device.vendorId)}:${hex4(device.productId)}${device.serialNumber ? `, S/N ${device.serialNumber}` : ''}`);
  if (DEMO && info && !state.file) import('./demo.js').then(({ demoFirmware }) => loadFile(demoFirmware(info.model)));
  render();
}

async function chooseDevice() {
  try {
    selectDevice(await state.usb.requestDevice({ filters: USB_FILTERS }));
  } catch (e) {
    if (e.name !== 'NotFoundError') { state.deviceError = e.message; render(); }
  }
}

/* ------------------------------------------------------------------ file */

async function loadFile(file) {
  if (!file) return;
  const bytes = new Uint8Array(await file.arrayBuffer());
  state.file = { name: file.name, bytes, sha: '', warnings: [] };
  $('ack').checked = false;
  state.result = null;
  render();
  log(`Firmware: ${file.name}, ${bytes.length} bytes`);
  try {
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    state.file.sha = Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
    log(`SHA-256: ${state.file.sha}`);
  } catch {
    state.file.sha = '—';
  }
  render();
}

/* ------------------------------------------------------------------ update */

function requestGesture(kind) {
  return new Promise((resolve, reject) => {
    state.gesture = { kind, resolve, reject };
    render();
    $('gesture-btn').focus();
  });
}

async function onGestureClick() {
  const g = state.gesture;
  if (!g) return;
  try {
    const d = await state.usb.requestDevice({ filters: DFU_FILTERS });
    state.gesture = null;
    render();
    g.resolve(d);
  } catch (e) {
    if (e.name !== 'NotFoundError') log(`Device selection failed: ${e.message}`);
  }
}

function weightsFor(model, size) {
  const reads = (size / model.readChunk) * 5;
  return {
    check: 20,
    erase: Math.ceil(size / 0x10000) * 120,
    blank: reads,
    program: (size / model.writeChunk) * 14,
    verify: reads,
  };
}

async function startUpdate() {
  const { device, info, file } = state;
  if (!device || !file || state.busy) return;
  const ac = new AbortController();
  state.busy = true;
  state.abort = ac;
  state.result = null;
  state.stepState = {};
  render();

  let wakeLock = null;
  try { wakeLock = await navigator.wakeLock?.request('screen'); } catch { /* optional */ }

  const model = info.model;
  const weights = weightsFor(model, file.bytes.length);
  const totalWeight = Object.values(weights).reduce((a, b) => a + b, 0);
  const order = ['check', 'erase', 'blank', 'program', 'verify'];
  let flashStart = 0;
  let lastPaint = 0;
  log(`Starting update: ${model.name}, ${file.name}`);

  const setStep = (id, s) => { state.stepState[id] = s; };
  const on = {
    log,
    device: (d) => { state.device = d; state.info = identify(d, state.lastModel); render(); },
    gesture: (kind) => requestGesture(kind),
    step: (id, s) => {
      if (id === 'flash') {
        if (s === 'active') { setStep('check', 'active'); flashStart = performance.now(); }
        else order.forEach((p) => setStep(p, 'done'));
      } else {
        setStep(id, s);
      }
      render();
    },
    progress: ({ phase, done, total }) => {
      if (phase === 'done') return;
      const idx = order.indexOf(phase);
      order.forEach((p, i) => setStep(p, i < idx ? 'done' : i === idx ? 'active' : undefined));
      const now = performance.now();
      if (now - lastPaint < 100 && done !== total) return;
      lastPaint = now;
      const before = order.slice(0, idx).reduce((a, p) => a + weights[p], 0);
      const frac = (before + weights[phase] * (total ? done / total : 0)) / totalWeight;
      const pct = Math.min(100, frac * 100);
      $('progress').hidden = false;
      $('bar-fill').style.width = `${pct.toFixed(1)}%`;
      $('progress-label').textContent = `${t(STEP_LABEL[phase])} · ${total ? Math.floor((done / total) * 100) : 0}%`;
      const elapsed = (now - flashStart) / 1000;
      $('progress-eta').textContent = frac > 0.02 && elapsed > 2
        ? `${Math.floor(pct)}% · ${t('eta', { time: formatTime(elapsed / frac - elapsed) })}`
        : `${Math.floor(pct)}%`;
      render();
    },
  };

  try {
    const res = await runUpdate({ usb: state.usb, device, model, firmware: file.bytes, on, signal: ac.signal });
    $('bar-fill').style.width = '100%';
    $('progress-label').textContent = t('doneTitle');
    $('progress-eta').textContent = '100%';
    const name = model.name;
    let body;
    let button = t('again');
    let action = resetForNext;
    if (!res.restarted) {
      body = t('doneManual', { model: name });
    } else if (res.appDevice?.serialNumber) {
      body = `${t('doneRestarted', { model: name })} ${t('doneVersion', { serial: res.appDevice.serialNumber })}`;
    } else {
      body = `${t('doneRestarted', { model: name })} ${t('doneReconnect')}`;
      button = t('connect');
      action = () => { resetForNext(); chooseDevice(); };
    }
    state.result = { ok: true, title: t('doneTitle'), body, button, action };
    log('Update complete');
  } catch (e) {
    const cancelled = e instanceof AbortedError || e.code === 'aborted';
    for (const id of STEPS) if (state.stepState[id] === 'active') state.stepState[id] = 'failed';
    const busy = e.code === 'busy' || (e.code === 'open' && state.info?.mode === 'app');
    state.result = {
      ok: false,
      title: t('failTitle'),
      body: cancelled ? t('cancelled') : busy ? t('deviceBusy') : `${e.message}. ${t('failRetry')}`,
      button: t('retry'),
      action: () => { state.result = null; startUpdate(); },
    };
    log(cancelled ? 'Update cancelled' : `Update failed: ${e.code ? `[${e.code}] ` : ''}${e.message}`);
  } finally {
    state.busy = false;
    state.abort = null;
    state.gesture = null;
    try { await wakeLock?.release(); } catch { /* released */ }
    render();
  }
}

function resetForNext() {
  state.result = null;
  state.stepState = {};
  $('progress').hidden = true;
  render();
}

function cancelUpdate() {
  const flashing = ['erase', 'blank', 'program', 'verify'].some((p) => state.stepState[p] === 'active');
  if (flashing && !confirm(t('leaveWarning'))) return;
  state.abort?.abort();
  if (state.gesture) {
    const g = state.gesture;
    state.gesture = null;
    g.reject(new AbortedError());
  }
}

/* ------------------------------------------------------------------ wiring */

async function init() {
  initLang(pref('lang'));
  if (DEMO) {
    const { demoUsb } = await import('./demo.js');
    state.usb = demoUsb(params.get('demo'));
  } else if (webUsbAvailable() && window.isSecureContext) {
    state.usb = navigator.usb;
  }
  $('nav').href = `batch.html${DEMO ? '?demo' : ''}`;
  applyStrings();

  $('lang').onclick = () => {
    setLang(getLang() === 'zh' ? 'en' : 'zh');
    pref('lang', getLang());
    applyStrings();
  };
  $('theme').onclick = () => {
    const next = currentTheme() === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    pref('theme', next);
  };

  $('connect').onclick = chooseDevice;
  $('change').onclick = chooseDevice;
  $('file').onchange = (e) => loadFile(e.target.files[0]);
  $('file-change').onclick = () => { $('file').value = ''; $('file').click(); };
  $('ack').onchange = render;
  $('start').onclick = startUpdate;
  $('cancel').onclick = cancelUpdate;
  $('gesture-btn').onclick = onGestureClick;
  $('result-btn').onclick = () => state.result?.action();
  $('copy-hash').onclick = () => copy(state.file?.sha, $('copy-hash'), 'copy');
  $('copy-log').onclick = (e) => { e.preventDefault(); copy(logLines.join('\n'), $('copy-log'), 'copyLog'); };

  const drop = $('drop');
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => {
    e.preventDefault();
    drop.classList.remove('over');
    loadFile(e.dataTransfer.files[0]);
  });

  window.addEventListener('beforeunload', (e) => {
    if (state.busy) { e.preventDefault(); e.returnValue = t('leaveWarning'); }
  });

  if (!state.usb) return;
  state.usb.addEventListener('disconnect', (e) => {
    if (!state.busy && e.device === state.device) {
      state.device = null;
      state.info = null;
      state.deviceError = t('deviceGone');
      render();
    }
  });
  state.usb.addEventListener('connect', (e) => {
    if (!state.busy && !state.device) selectDevice(e.device);
  });
  const known = (await state.usb.getDevices()).filter((d) => identify(d));
  if (known.length) selectDevice(known.find((d) => identify(d).mode === 'dfu') ?? known[0]);
}

async function copy(text, button, key) {
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    button.textContent = t('copied');
    setTimeout(() => { button.textContent = t(key); }, 1200);
  } catch { /* clipboard blocked */ }
}

init();
