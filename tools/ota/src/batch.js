// Batch page controller.

import { MODELS, USB_FILTERS, inspectFirmware } from './devices.js';
import { BatchEngine, ACTIVE, MAX_ATTEMPTS } from './batch-engine.js';
import { webUsbAvailable } from './usb.js';
import { initLang, getLang, setLang, t } from './i18n.js';
import { ledIcon } from './led.js';
import { stationFiles, policyValue, detectOs, download, STATION_ORIGIN } from './station.js';

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const DEMO = params.has('demo');

const WIKI = {
  en: 'https://wiki.sipeed.com/hardware/en/logic_analyzer/slogic32u3/Hardware_Specification.html#Firmware-Update',
  zh: 'https://wiki.sipeed.com/hardware/zh/logic_analyzer/slogic32u3/Hardware_Specification.html#%E6%9B%B4%E6%96%B0%E5%9B%BA%E4%BB%B6',
};
const PHASE = { check: 'sCheck', erase: 'sErase', blank: 'sBlank', program: 'sProgram', verify: 'sVerify' };
const PHASE_WEIGHT = { check: [0, 1], erase: [1, 5], blank: [6, 14], program: [20, 66], verify: [86, 14] };

const state = { usb: null, engine: null, modelId: 'slogic32u3', file: null, os: 'linux' };

function pref(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(`slogic-ota-${key}`);
    localStorage.setItem(`slogic-ota-${key}`, value);
  } catch { /* no storage */ }
  return null;
}

/* ------------------------------------------------------------------ log */

const logLines = [];
function log(msg) {
  logLines.push(`[${new Date().toLocaleTimeString([], { hour12: false })}] ${msg}`);
  if (logLines.length > 2000) logLines.splice(0, logLines.length - 2000);
  const el = $('log');
  el.textContent = logLines.join('\n');
  el.scrollTop = el.scrollHeight;
}

/* ------------------------------------------------------------------ render */

function applyStrings() {
  document.documentElement.lang = getLang() === 'zh' ? 'zh-CN' : 'en';
  document.title = t('batchTitle');
  for (const el of document.querySelectorAll('[data-i18n]')) el.textContent = t(el.dataset.i18n);
  for (const el of document.querySelectorAll('[data-i18n-title]')) {
    el.title = t(el.dataset.i18nTitle);
    el.setAttribute('aria-label', el.title);
  }
  $('lang').textContent = t('langToggle');
  $('wiki').href = WIKI[getLang()];
  $('legend-app').replaceChildren(ledIcon('app'));
  $('legend-dfu').replaceChildren(ledIcon('dfu'));
  renderStation();
  render();
}

function render() {
  const e = state.engine;
  const model = MODELS[state.modelId];

  if (!window.isSecureContext && !DEMO) showBanner(t('insecureTitle'), t('insecureBody'));
  else if (!state.usb) showBanner(t('noWebUsbTitle'), t('noWebUsbBody'));
  else if (DEMO) showBanner(t('demoBanner'), '', true);
  else $('banner').hidden = true;

  for (const b of document.querySelectorAll('#model button')) {
    const on = b.dataset.model === state.modelId;
    b.classList.toggle('on', on);
    b.setAttribute('aria-checked', on);
    b.disabled = !!e?.running;
  }
  $('update-normal-row').hidden = !model.reconfig;
  $('update-normal').disabled = !!e?.running;

  const f = state.file;
  $('file-label').textContent = f ? f.name : t('fileHint');
  $('drop').classList.toggle('has-file', !!f);
  $('file-meta').hidden = !f;
  if (f) {
    $('file-size').textContent = `${(f.bytes.length / 1048576).toFixed(2)} MiB`;
    $('file-hash').textContent = f.sha ? `SHA-256 ${f.sha.slice(0, 16)}…` : '';
    $('file-hash').title = f.sha;
    f.warnings = inspectFirmware(f.bytes, f.name, model);
  }
  const warnings = f?.warnings ?? [];
  $('file-warnings').hidden = !warnings.length;
  $('file-warnings').replaceChildren(...warnings.map((w) => {
    const li = document.createElement('li');
    li.textContent = t({ 'not-bitstream': 'warnNotBitstream', 'size-unusual': 'warnSize', 'name-other-model': 'warnName' }[w], { model: model.name });
    return li;
  }));
  $('ack-row').hidden = !warnings.length;
  $('ack-text').textContent = t('ackWarnings', { model: model.name });
  $('drop').classList.toggle('disabled', !!e?.running);

  const canStart = !!state.usb && !!f && (!warnings.length || $('ack').checked);
  const run = $('run');
  run.textContent = e?.running ? t('pauseBatch') : t('startBatch');
  run.classList.toggle('pause', !!e?.running);
  run.disabled = !e?.running && !canStart;
  $('run-state').textContent = e?.running ? t('batchRunning') : e?.startedOnce ? t('batchPaused') : t('batchIdle');

  const c = e?.counts() ?? { done: 0, active: 0, waiting: 0, failed: 0, total: 0 };
  $('c-done').textContent = c.done;
  $('c-active').textContent = c.active;
  $('c-waiting').textContent = c.waiting;
  $('c-failed').textContent = c.failed;
  $('c-session').textContent = c.total;

  const boards = e?.boards ?? [];
  $('no-boards').hidden = boards.length > 0;
  $('failed-hint').hidden = !(c.failed > 0 && c.active === 0);
  $('clear').disabled = !boards.some((b) => b.state === 'removed');
  $('add').disabled = !state.usb;
  renderBoards(boards);
}

function showBanner(title, body, info = false) {
  $('banner').hidden = false;
  $('banner').classList.toggle('info', info);
  $('banner-title').textContent = title;
  $('banner-body').textContent = body;
}

const cards = new Map();

function renderBoards(boards) {
  const list = $('boards');
  // Newest first; unplugged boards sink to the end.
  const order = [...boards].sort((a, b) => (a.state === 'removed') - (b.state === 'removed') || b.id - a.id);
  for (const [id, el] of cards) if (!boards.some((b) => b.id === id)) { el.remove(); cards.delete(id); }
  order.forEach((b, i) => {
    let el = cards.get(b.id);
    if (!el) {
      el = document.createElement('div');
      el.innerHTML = '<div class="b-top"><span class="b-id"></span><span class="b-led"></span></div>'
        + '<div class="b-status"></div><div class="b-sub"></div><div class="b-bar"><div></div></div>'
        + '<button class="ghost small b-retry" type="button"></button>';
      el.querySelector('.b-retry').onclick = () => state.engine.retry(b);
      cards.set(b.id, el);
    }
    if (list.children[i] !== el) list.insertBefore(el, list.children[i] ?? null);
    fillCard(el, b);
  });
}

function fillCard(el, b) {
  const kind = b.state === 'done' ? 'done' : ACTIVE.has(b.state) ? 'active'
    : b.state === 'failed' || b.state === 'wrong-model' ? 'failed'
    : b.state === 'removed' ? (b.message === 'interrupted' ? 'removed interrupted' : 'removed') : 'waiting';
  el.className = `board ${kind}`;
  el.querySelector('.b-id').textContent = `#${b.id}  ${b.model.name}`;
  const led = el.querySelector('.b-led');
  const mode = b.state === 'removed' ? null : ['switching', 'restarting', 'retrying'].includes(b.state) ? 'dfu' : b.mode;
  if (led.dataset.mode !== String(mode)) {
    led.dataset.mode = String(mode);
    led.replaceChildren(...(mode ? [ledIcon(mode)] : []));
  }
  let status = '';
  let sub = '';
  let pct = null;
  switch (b.state) {
    case 'flashing': {
      const [base, span] = PHASE_WEIGHT[b.phase] ?? [0, 1];
      const frac = b.total ? b.done / b.total : 0;
      pct = base + span * frac;
      status = t('bFlashing', { phase: t(PHASE[b.phase] ?? 'sCheck'), pct: Math.floor(frac * 100) });
      sub = elapsed(b.started);
      break;
    }
    case 'switching': status = t('bSwitching'); break;
    case 'retrying': status = t('bRetrying', { n: b.attempts + 1, max: MAX_ATTEMPTS }); sub = b.message; break;
    case 'restarting': status = t('bRestarting'); pct = 100; break;
    case 'done':
      status = t(b.message === 'already' ? 'bDoneAlready' : b.message === 'replug' ? 'bDoneReplug' : 'bDone');
      sub = b.finished ? `${((b.finished - b.started) / 1000).toFixed(0)} s` : '';
      if (b.serial && b.mode === 'app') sub = sub ? `${sub} · S/N ${b.serial}` : `S/N ${b.serial}`;
      pct = 100;
      break;
    case 'failed': status = b.attempts > 1 ? t('bFailedN', { n: b.attempts }) : t('bFailed'); sub = b.message; break;
    case 'wrong-model': status = t('bWrongModel'); break;
    case 'removed': status = t(b.message === 'interrupted' ? 'bInterrupted' : 'bRemoved'); break;
    case 'ready': status = t('bReady'); break;
    case 'waiting':
      status = t(b.message === 'press-mode' ? 'bPressMode'
        : state.engine.running && !state.engine.updateNormal ? 'bWaitingOff' : 'bWaiting');
      break;
    default: status = t('bNew');
  }
  el.querySelector('.b-status').textContent = status;
  el.querySelector('.b-sub').textContent = sub;
  const bar = el.querySelector('.b-bar');
  bar.hidden = pct === null;
  if (pct !== null) bar.firstChild.style.width = `${pct.toFixed(1)}%`;
  const retry = el.querySelector('.b-retry');
  retry.hidden = b.state !== 'failed';
  retry.textContent = t('retry1');
}

function elapsed(since) {
  return since ? `${Math.round((Date.now() - since) / 1000)} s` : '';
}

function stationOrigin() {
  return STATION_ORIGIN;
}

function renderStation() {
  const os = state.os;
  for (const b of document.querySelectorAll('#os-tabs button')) b.classList.toggle('on', b.dataset.os === os);
  const files = stationFiles(os, stationOrigin());
  $('st-remove').hidden = !files.remove;
  const steps = {
    windows: ['stWin1', 'stWin2', 'stWin3'],
    macos: ['stMac1', 'stMac2', 'stMac3'],
    linux: ['stLinux1', 'stLinux2', 'stLinux3'],
  }[os];
  $('st-steps').replaceChildren(...[...steps, 'stCheck'].map((k) => {
    const li = document.createElement('li');
    li.textContent = t(k, { file: files.install.name });
    return li;
  }));
  $('st-origin').textContent = t('stOrigin', { origin: stationOrigin() })
    + (location.origin === stationOrigin() || DEMO ? '' : ` ${t('stElsewhere', { here: location.origin })}`);
  $('policy').textContent = JSON.stringify({ WebUsbAllowDevicesForUrls: policyValue(stationOrigin()) }, null, 2);
}

/* ------------------------------------------------------------------ actions */

async function loadFile(file) {
  if (!file || state.engine?.running) return;
  const bytes = new Uint8Array(await file.arrayBuffer());
  state.file = { name: file.name, bytes, sha: '', warnings: [] };
  $('ack').checked = false;
  log(`Firmware: ${file.name}, ${bytes.length} bytes`);
  configure();
  try {
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    state.file.sha = Array.from(new Uint8Array(digest), (x) => x.toString(16).padStart(2, '0')).join('');
    log(`SHA-256: ${state.file.sha}`);
  } catch { /* no hash */ }
  render();
}

function configure() {
  state.engine?.configure({
    model: MODELS[state.modelId],
    firmware: state.file?.bytes ?? null,
    updateNormal: $('update-normal').checked,
  });
  render();
}

function toggleRun() {
  const e = state.engine;
  if (!e) return;
  if (e.running) e.stop();
  else { configure(); e.start(); }
  render();
}

async function addDevice() {
  try {
    const d = await state.usb.requestDevice({ filters: USB_FILTERS });
    state.engine.add(d);
  } catch (err) {
    if (err.name !== 'NotFoundError') log(`Device selection failed: ${err.message}`);
  }
}

/* ------------------------------------------------------------------ demo */

async function startDemo(param) {
  const { demoUsb, demoFirmware } = await import('./demo.js');
  const modelId = param === '16u3' ? 'slogic16u3' : 'slogic32u3';
  const usb = demoUsb(param, { permitAll: true, boards: 0 });
  window.slogicDemo = usb; // demo only: lets tests inject faults
  // Factory boards arrive in update mode.
  usb.plug(modelId, 'dfu', true);
  usb.plug(modelId, 'dfu', true);
  usb.plug(modelId, 'dfu', true);
  state.modelId = modelId;
  // Simulated operator: unplug finished boards and plug in blank ones.
  let plugged = 3;
  setInterval(() => {
    const e = state.engine;
    if (!e?.running) return;
    const done = e.boards.find((b) => b.state === 'done' && Date.now() - (b.finished || 0) > 2500);
    if (done) usb.unplug(done.device);
    else if (plugged < 9 && e.boards.filter((b) => b.state !== 'removed').length < 4) {
      plugged++;
      usb.plug(modelId, 'dfu');
    }
  }, 1200);
  setTimeout(() => loadFile(demoFirmware(MODELS[modelId])), 0);
  return usb;
}

/* ------------------------------------------------------------------ wiring */

async function init() {
  initLang(pref('lang'));
  state.os = detectOs();
  state.modelId = pref('batch-model') === 'slogic16u3' ? 'slogic16u3' : 'slogic32u3';
  if (DEMO) state.usb = await startDemo(params.get('demo'));
  else if (webUsbAvailable() && window.isSecureContext) state.usb = navigator.usb;
  $('nav').href = `index.html${DEMO ? '?demo' : ''}`;

  if (state.usb) {
    state.engine = new BatchEngine({ usb: state.usb, log });
    state.engine.addEventListener('change', render);
  }
  applyStrings();

  $('lang').onclick = () => {
    setLang(getLang() === 'zh' ? 'en' : 'zh');
    pref('lang', getLang());
    applyStrings();
  };
  $('theme').onclick = () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === 'dark'
      : matchMedia('(prefers-color-scheme: dark)').matches;
    document.documentElement.dataset.theme = dark ? 'light' : 'dark';
    pref('theme', document.documentElement.dataset.theme);
  };
  for (const b of document.querySelectorAll('#model button')) {
    b.onclick = () => {
      state.modelId = b.dataset.model;
      pref('batch-model', state.modelId);
      $('ack').checked = false;
      configure();
    };
  }
  $('file').onchange = (ev) => loadFile(ev.target.files[0]);
  $('ack').onchange = render;
  $('update-normal').onchange = configure;
  $('run').onclick = toggleRun;
  $('add').onclick = addDevice;
  $('clear').onclick = () => state.engine.clearRemoved();
  for (const b of document.querySelectorAll('#os-tabs button')) {
    b.onclick = () => { state.os = b.dataset.os; renderStation(); };
  }
  $('st-install').onclick = () => download(stationFiles(state.os, stationOrigin()).install);
  $('st-remove').onclick = () => {
    const f = stationFiles(state.os, stationOrigin()).remove;
    if (f) download(f);
  };
  $('copy-log').onclick = async (ev) => {
    ev.preventDefault();
    try { await navigator.clipboard.writeText(logLines.join('\n')); } catch { /* blocked */ }
  };
  const drop = $('drop');
  drop.addEventListener('click', (ev) => { if (state.engine?.running) ev.preventDefault(); });
  drop.addEventListener('dragover', (ev) => { ev.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (ev) => {
    ev.preventDefault();
    drop.classList.remove('over');
    loadFile(ev.dataTransfer.files[0]);
  });
  window.addEventListener('beforeunload', (ev) => {
    if (state.engine?.boards.some((b) => ACTIVE.has(b.state))) { ev.preventDefault(); ev.returnValue = t('leaveWarning'); }
  });
  // Elapsed times tick even when nothing else changes.
  setInterval(() => { if (state.engine?.boards.some((b) => b.state === 'flashing')) render(); }, 1000);

  if (state.engine) {
    configure();
    await state.engine.attach();
    render();
  }
}

init();
