# SLogic Firmware Update (web)

Static web pages that update the application firmware (`app.bin`) of
SLogic16U3 and SLogic32U3 over WebUSB:

- `index.html`: one device; select it, choose the file, click **Update firmware**.
- `batch.html`: many boards in parallel for production (see below).

Light/dark theme and English/中文 included.

## Browser support

WebUSB is available in **Chrome, Edge, Opera, Brave and other Chromium-based
browsers on desktop** (Windows, macOS, Linux). Firefox and Safari do not
implement WebUSB; the page still opens there and tells the user to switch
browsers. The page must be served over **https://** or from
**http://localhost** (browsers only allow USB access on secure origins).

## Run it

No build step; serve the directory as static files:

```sh
cd tools/ota
python3 serve.py          # http://localhost:8000 (this computer)
python3 serve.py --lan    # https://<lan-ip>:8443 for colleagues on the LAN
```

USB access needs a secure page, and a plain `http://<lan-ip>` address is not
one, so `--lan` serves HTTPS with a self-signed certificate (generated with
openssl into `.certs/`, covering this computer's IPv4 addresses). Each visitor
accepts the browser's certificate warning once.

For a public deployment, publish the directory as is (e.g. GitHub Pages).

After changing any file under `src/` or `style.css`, run `python3 stamp.py`:
it puts content hashes into the asset URLs of both pages (an import map), so
browsers never mix cached old modules with new ones. The tests fail if a
stamp is out of date.

**Demo mode:** `http://localhost:8000/?demo` (SLogic32U3) or `?demo=16u3`
simulates a device and its flash, so the whole flow can be previewed without
hardware.

## How an update works

| Step | SLogic32U3 | SLogic16U3 |
|---|---|---|
| Enter update mode (DFU) | automatic: USB RECONFIG request | user presses MODE |
| Check flash | bridge reset, JEDEC ID, flash size check | same |
| Erase / blank check / write / verify | 64 KiB erases, read back blank, page program (48 B per transaction), full read-back compare | same, 12 B per transaction |
| Restart | automatic: USB RECONFIG request | user re-plugs |

| Mode | USB ID |
|---|---|
| SLogic16U3 normal / update | 359f:3031 / 359f:30f1 |
| SLogic32U3 normal / update | 359f:3032 / 359f:30f2 (early update firmware used 30f1) |

A browser only lets a page open devices the user picked in its device dialog.
The update-mode device ("SLogic DFU") has a different USB ID and no serial
number, so the browser cannot remember it: each update asks for one extra click
("Select update-mode device"). Everything else runs on its own.

Measured on an SLogic32U3 (Linux, 1.7 MB image): about 40 s in total, of
which erase 2 s, blank check 6 s, write 24 s, verify 6 s.

The flash protocol (USB-SPI bridge packets, SPI NOR commands, chunk sizes) is
taken from the production flasher in the SLogic production-test tools
(`slogicpt/dfu`, `resources/products/*/product.toml [ota]`).

## Batch update (`batch.html`)

For production: choose the model and the firmware once, press **Start**, then
keep plugging in boards. Every board is updated in parallel as soon as it
appears; the page lists each board with its state and a progress bar, plus
counters (done / in progress / waiting / failed / completed this session).

The page mirrors the board's status LED so the operator can work by the LED:

| LED | Meaning |
|---|---|
| steady cyan | done (or normal mode): unplug it |
| cyan + slow red blink | update mode: being updated, leave it plugged in |

- New boards from the factory arrive in update mode and are written as soon
  as they are plugged in; a SLogic32U3 then restarts into normal mode.
- Boards in normal mode are left alone by default (on a production line that
  is usually a board that is already done). For rework or returned units,
  tick the rework option: SLogic32U3 boards in normal mode are then switched
  to update mode automatically. A board that already reports the new
  firmware S/N is never updated again.
- SLogic16U3 boards are updated when they arrive in update mode (MODE button);
  when done they stay in update mode until re-plugged.
- Boards of the other model are flagged and left alone.

**Station setup.** The update-mode device has no USB serial number, so a
browser normally asks for permission for every board. The batch page's
"Station setup" section installs the browser policy `WebUsbAllowDevicesForUrls`
for the site the pages are published on, `https://slogic.sipeed.com`
(`STATION_ORIGIN` in `src/station.js`; any path on that site), so boards are
picked up without any click. A web page
cannot change system settings itself, so the buttons download a file to run
once:

| OS | Install | Remove |
|---|---|---|
| Windows | `slogic-webusb-install.reg`: double-click, confirm (admin) | `slogic-webusb-remove.reg` |
| macOS | `slogic-webusb.mobileconfig`: open, then approve in System Settings › Privacy & Security › Profiles | remove the profile there |
| Linux | `sudo sh slogic-webusb-install.sh` (also installs the udev rule) | `sudo sh slogic-webusb-remove.sh` |

Chrome and Edge are covered (plus Chromium and Brave on Linux); restart the
browser afterwards and check `chrome://policy`. While installed, the browser
shows "managed by your organization". Without the policy, or when the page is
opened from another address (e.g. `serve.py --lan`), "Add device manually"
adds boards one at a time through the browser's dialog.

Preview without hardware: `batch.html?demo` (simulated operator plugging and
unplugging boards) or `batch.html?demo=16u3`.

## Platform notes

- **Linux:** the browser needs access to the USB device. Install a udev rule
  covering the update-mode IDs too, then re-plug:

  ```sh
  sudo tee /etc/udev/rules.d/60-slogic.rules >/dev/null <<'EOF'
  SUBSYSTEM=="usb", ATTRS{idVendor}=="359f", ATTRS{idProduct}=="0300|3031|3032|30f1|30f2", MODE="0666", TAG+="uaccess"
  EOF
  sudo udevadm control --reload-rules && sudo udevadm trigger
  ```
- **Windows:** WebUSB needs the WinUSB driver on the update-mode device. If it
  does not appear in the browser's device dialog, check Device Manager.
- Close SLogicView, PulseView, AllLogic, ngscopeclient and sigrok-cli first:
  a device that another program has open cannot be switched to update mode.

## Files

```text
index.html, style.css, favicon.svg   the page
batch.html        batch update page
src/app.js        page controller (UI state, progress, prompts)
src/batch.js      batch page controller
src/batch-engine.js  batch logic: device tracking, parallel updates, board states
src/led.js        status LED icon
src/updater.js    the update sequence: mode switch, recovery, flash, restart
src/flash.js      SPI NOR operations and erase/program/verify
src/spi.js        USB-SPI bridge packets and registers
src/usb.js        WebUSB bulk transport, RECONFIG request
src/devices.js    model table, USB IDs, update parameters, file checks
src/i18n.js       English / Chinese strings
src/demo.js       ?demo: simulated WebUSB device and flash
test/             node tests (node --test test/)
```

## Tests

```sh
node --test test/
```

- `replay.test.mjs` replays USB transcripts recorded from the reference Python
  flasher (`test/gen_transcript.py`) and requires byte-identical traffic, plus
  error paths (verify mismatch, hung bus, cancel). To record a new transcript:

  ```sh
  python3 test/gen_transcript.py <SLogic16U3-tools dir> /tmp/t.json --size 0x10200 --write-chunk 48
  EXTRA_TRANSCRIPTS=/tmp/t.json node --test test/
  ```
- `updater.test.mjs` runs the whole update for both models against the demo
  device and checks the flash content.
- `batch.test.mjs` runs batches of simulated boards (mixed modes, parallel,
  unplug/replug, already-updated and wrong-model boards).
- `devices.test.mjs` covers model identification and firmware warnings.
