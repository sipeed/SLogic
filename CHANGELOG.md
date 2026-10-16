# Changelog

Release notes for the SLogic software package (SLogicView, PulseView,
AllLogic, ngscopeclient and sigrok-cli). Releases are tagged `release-X.Y.Z`
and published at https://github.com/sipeed/SLogic/releases; the section for
each version below is its release page text. Supported hardware, system
requirements and installation are in the [README](README.md). A Chinese
translation of each section is kept in [CHANGELOG.zh-CN.md](CHANGELOG.zh-CN.md)
and appended to the release page.

## v2.3.2 — 2026-10-16

SLogic 2.3.2 is a maintenance release: a fix for Windows and a new minimum
firmware for SLogic32U3. System requirements, downloads and installation are
unchanged; see the
[README](https://github.com/sipeed/SLogic#readme).

> [!IMPORTANT]
> **SLogic32U3 now requires firmware S/N {{firmware.slogic32u3.min}} or newer.** This
> firmware brings the improvements of S/N 202610140927 and adds automatic
> recovery at startup: if the capture path does not come up after power-on or
> reset, the analyzer re-initializes itself, and a capture starts only once it
> is ready. To update, see the SLogic wiki ([English]({{firmware.slogic32u3.update_guide.en}}) · [中文]({{firmware.slogic32u3.update_guide.zh}})).

### Fixes

- **Windows: quiet, lighter capture loop.** sigrok-cli, PulseView and
  SLogicView no longer print repeated "WaitForMultipleObjectsEx failed"
  messages during a capture, and no longer spend CPU time on them. Captured
  data was not affected. AllLogic and ngscopeclient were not affected.

## v2.3.1 — 2026-10-16

SLogic 2.3.1 is a maintenance release: a uniform sample clock on SLogic32U3
and better analog (ADC) support in ngscopeclient. System requirements,
downloads and installation are unchanged; see the
[README](https://github.com/sipeed/SLogic#readme).

> [!IMPORTANT]
> **SLogic32U3 requires firmware S/N 202610140927 or newer** (unchanged from
> 2.3.0). To update, see the SLogic wiki ([English](https://wiki.sipeed.com/hardware/en/logic_analyzer/slogic32u3/Hardware_Specification.html#Firmware-Update) · [中文](https://wiki.sipeed.com/hardware/zh/logic_analyzer/slogic32u3/Hardware_Specification.html#%E6%9B%B4%E6%96%B0%E5%9B%BA%E4%BB%B6)).

### Improvements

- **Uniform sample clock on SLogic32U3.** Every sample rate from 5 to
  800 MHz is now generated from the analyzer's 800 MHz clock, so all of them
  share the same clock source; 4ch@1400 MHz keeps its dedicated clock. This
  applies to every application.
- **ngscopeclient: analog channel groups (ADC).**
  - New **ADC bit order** setting in the Stream Browser: *Auto* (CH0 = MSB
    for real signals, matching the ADC module's wiring, and CH0 = LSB for the
    built-in test patterns), *CH0 = MSB* or *CH0 = LSB*.
  - The analog edge trigger now fires only on the selected edge (Rising,
    Falling or Any) and has built-in hysteresis, for a stable display of
    noisy signals.
  - While a group is analog, captures use the ADC's 800 MHz clock so samples
    stay in step with the ADC; 1400 MHz is not offered in this mode.

### Other

- The libsigrok udev rules include the SLogic32U3, for distributions that
  package libsigrok.

## v2.3.0 — 2026-10-14

SLogic 2.3.0 is the first official release of the SLogic software package for
Windows, macOS and Linux: five applications built on one shared driver core,
with full-speed streaming, a hardware-speed trigger and exact sample counts on
every supported analyzer. See the [README](https://github.com/sipeed/SLogic#readme)
for system requirements and installation.

> [!IMPORTANT]
> **SLogic32U3 requires firmware S/N 202610140927 or newer.** This firmware
> provides a clean capture start and stop in every channel mode; please update
> before using 2.3.0. The firmware S/N is shown as `[S/N: …]` in each
> application's device list and by `sigrok-cli -d sipeed-slogic-analyzer --scan`.
> To update, see the SLogic wiki ([English](https://wiki.sipeed.com/hardware/en/logic_analyzer/slogic32u3/Hardware_Specification.html#Firmware-Update) · [中文](https://wiki.sipeed.com/hardware/zh/logic_analyzer/slogic32u3/Hardware_Specification.html#%E6%9B%B4%E6%96%B0%E5%9B%BA%E4%BB%B6)).

### Downloads

| Application | Windows x64 | macOS (Apple Silicon) | Linux x86_64 |
|---|---|---|---|
| SLogicView (recommended) | `SLogicView-SLogic-2.3.0-windows-x86_64.exe` | `SLogicView-SLogic-2.3.0-macos-arm64.dmg` | `SLogicView-SLogic-2.3.0-linux-x86_64.AppImage` |
| PulseView | `PulseView-…-windows-x86_64.exe` | `PulseView-…-macos-arm64.dmg` | `PulseView-…-linux-x86_64.AppImage` |
| AllLogic | `AllLogic-…-windows-x86_64.exe` | `AllLogic-…-macos-arm64.dmg` | `AllLogic-…-linux-x86_64.AppImage` |
| ngscopeclient | `ngscopeclient-…-windows-x86_64.exe` | `ngscopeclient-…-macos-arm64.dmg` | `ngscopeclient-…-linux-x86_64.AppImage` (glibc ≥ 2.39) |
| sigrok-cli | `sigrok-cli-…-windows-x86_64.exe` | `sigrok-cli-…-macos-arm64.zip` | `sigrok-cli-…-linux-x86_64.AppImage` |

### Supported hardware

| Device | Max sample rate | Status |
|---|---|---|
| SLogic32U3 (10 Gbps) | 4ch 1400 MHz · 8ch 800 · 16ch 400 · 32ch 200 | ✅ Tested in this release (firmware 202610140927 or newer) |
| SLogic16U3 (5 Gbps) | 4ch 800 MHz · 8ch 400 · 16ch 200 | ✅ Tested in this release |
| SLogic Combo 8 (USB 2.0) | 2ch 160 MHz · 4ch 80 · 8ch 40 | Supported |

The device name shows the USB link it is connected at, e.g.
`(10G) Sipeed SLogic32 U3`, and the available sample rates follow that link
(SLogic32U3 on a 5 Gbps port: 4ch 800 · 8ch 400 · 16ch 200 · 32ch 100 MHz).

### Highlights

- **Full-speed streaming on every platform.** SLogic32U3 sustains its full
  USB bandwidth of 800 MB/s on Windows, macOS and Linux (8ch@800 MHz to
  32ch@200 MHz, and 4ch@1400 MHz), for a fixed length or continuously.
- **One driver core for every application.** Capture, trigger, sample
  accounting and error recovery are implemented once and shared, so all five
  applications behave consistently and receive the same improvements.
- **Hardware-speed trigger.** Per-channel low / high / rising / falling / any
  edge conditions keep up with 4ch@1400 MHz and place the trigger exactly at
  the chosen pre-trigger position (default 10%; `captureratio` in sigrok-cli,
  0–90% slider in AllLogic).
- **Exact captures.** Every channel mode delivers exactly the requested number
  of samples; continuous capture (`sigrok-cli --continuous`, AllLogic loop
  mode) runs until you stop it.
- **Link-aware.** The connected USB link (10G / 5G / USB 2.0) is shown in the
  device name and the sample rate list adapts to it automatically.
- **Responsive control.** Stop takes effect immediately, including while
  waiting for a trigger, and the analyzer is picked up again automatically
  after it reconnects.
- **Throughput report.** Each capture ends with a one-line summary
  (`slogic-report v1`: rate, sample count, trigger position), and log level 4
  (`-l 4`) shows the live rate every 200 ms.

### Upgrading from a 2.x preview build

- **SLogicView:** larger 14 px interface text and panel buttons; the Protocol
  Decoders panel opens when you add a decoder; device settings stay in sync
  after reconnecting; smoother Run/Stop, including stopping while waiting for
  a trigger.
- **AllLogic:** trigger support with an adjustable trigger position (0–90%),
  and about 3.8× faster 4-channel processing.
- **ngscopeclient:** accurate 4-channel display and smooth handling of very
  deep captures.
- **sigrok-cli:** exact sample counts for any requested length in 4-channel
  mode.

### Notes

- Triggers are set per channel and combined with AND. Multi-stage trigger
  sequences (DSView's advanced trigger mode) are not part of this release.
- For the full SLogic32U3 sample rates, connect it directly to a 10 Gbps
  USB port with a 10 Gbps-rated cable.
- SLogic16U3 with firmware 202512261505: a 4-channel capture at 800 MHz may
  begin with a few repeated samples. An updated firmware is in preparation;
  all other modes are unaffected.

### Quality assurance

Every release build was validated on real hardware with our automated test
suite on Windows, macOS and Linux, covering throughput in each channel mode,
exact sample counts, continuous streaming, trigger placement, repeated
open/capture/close cycles and protocol decoding:

| Device | Linux | macOS | Windows |
|---|---|---|---|
| SLogic32U3 at 10 Gbps | ✅ | ✅ | ✅ |
| SLogic32U3 at 5 Gbps | ✅ | ✅ | ✅ |
| SLogic16U3 at 5 Gbps | ✅ | ✅ | ✅ |

## Preview builds (2.0.0 – 2.2.0)

2.0.0, 2.1.0 and 2.2.0 were preview builds of the all-in-one package. Their
improvements, including full-speed capture on Windows, the adjustable
ngscopeclient threshold, the sigrok-cli automation plugin and deep-capture
performance, are all part of 2.3.0.
