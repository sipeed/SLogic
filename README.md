# SLogic

Desktop software for the Sipeed SLogic USB logic analyzers, for Windows, macOS
and Linux. Download it from
[Releases](https://github.com/sipeed/SLogic/releases/latest); what changed in
each version is in [CHANGELOG.md](CHANGELOG.md).

## Applications

Every release ships the same five applications for each platform. They all use
the same SLogic driver core, so device support, sample rates and capture
behaviour are identical across them.

| Application | Use it for |
|---|---|
| **SLogicView** | The recommended GUI: capture, trigger and protocol decoding, based on PulseView with a reworked UI. |
| **PulseView** | The classic sigrok GUI, for users who prefer the original interface. |
| **AllLogic** | A DSView-style GUI. |
| **ngscopeclient** | Waveform analysis on very deep captures (hundreds of millions of samples). |
| **sigrok-cli** | Command line: scripting, automation and CI. |

## Supported hardware

| Device | USB ID | Interface | Max sample rate by channel count | Status |
|---|---|---|---|---|
| **SLogic32U3** | 359f:3032 | USB 3.2 Gen 2 (10 Gbps) | 4ch 1400 MHz · 8ch 800 · 16ch 400 · 32ch 200 | ✅ Tested |
| **SLogic16U3** | 359f:3031 | USB 3.2 Gen 1 (5 Gbps) | 4ch 800 MHz · 8ch 400 · 16ch 200 | ✅ Tested |
| **SLogic Combo 8** | 359f:0300 | USB 2.0 | 2ch 160 MHz · 4ch 80 · 8ch 40 | Supported |

- **Tested**: validated on this device on Windows, macOS and Linux for every
  release. **Supported**: works with the same driver; not part of the current
  release's hardware test pass.
- **The USB link limits the sample rate.** The device name shows the link it
  negotiated, e.g. `(10G) Sipeed SLogic32 U3`, and the sample rate list is
  limited to what that link can carry:
  - SLogic32U3 on a 5 Gbps port: 4ch 800 MHz · 8ch 400 · 16ch 200 · 32ch 100.
  - Any U3 model on a USB 2.0 port: 320 MHz ÷ channel count (e.g. 8ch 40 MHz).

  For full speed, plug a SLogic32U3 directly into a 10 Gbps port (often marked
  *SS10* or red) with a 10 Gbps-rated cable, not through a hub or dock.
- **Firmware:** SLogic32U3 requires firmware S/N **202610150528** or newer. The
  firmware S/N is the `[S/N: …]` shown by
  `sigrok-cli -d sipeed-slogic-analyzer --scan` and in every application's
  device list. To update the firmware, see the SLogic wiki ([English](https://wiki.sipeed.com/hardware/en/logic_analyzer/slogic32u3/Hardware_Specification.html#Firmware-Update) · [中文](https://wiki.sipeed.com/hardware/zh/logic_analyzer/slogic32u3/Hardware_Specification.html#%E6%9B%B4%E6%96%B0%E5%9B%BA%E4%BB%B6)).

## System requirements

| Platform | Requirement | Files |
|---|---|---|
| **Windows** | Windows 10 or 11, x64 | `*-windows-x86_64.exe` |
| **macOS** | macOS 15 or later, Apple Silicon (M1 or later) | `*-macos-arm64.dmg`; sigrok-cli is a `.zip` |
| **Linux** | x86_64, any distribution | `*-linux-x86_64.AppImage`; ngscopeclient needs glibc 2.39 or newer (Ubuntu 24.04+, Debian 13+, Fedora 40+) |

## Installation

### Windows

Run the `.exe`. No driver installation is needed: the analyzer binds to
Windows' built-in WinUSB driver automatically the first time it is plugged in.

### macOS

Open the `.dmg` and drag the application to Applications. For sigrok-cli,
unzip the archive and run the `sigrok-cli` script inside it.

### Linux

Make the AppImage executable and run it:

```sh
chmod +x SLogicView-SLogic-*-linux-x86_64.AppImage
./SLogicView-SLogic-*-linux-x86_64.AppImage
```

To use the analyzer as a normal user, install this udev rule once, then
re-plug the analyzer:

```sh
sudo tee /etc/udev/rules.d/60-slogic.rules >/dev/null <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="359f", ATTRS{idProduct}=="0300|3031|3032", MODE="0666", TAG+="uaccess"
EOF
sudo udevadm control --reload-rules && sudo udevadm trigger
```

## For developers

This repository is a git superproject: the multi-platform build system is
tracked directly in `build/`, the shared SLogic driver core in `slogic/`, and
every product source is pinned as a git submodule under `sources/`.

### Get the workspace

```sh
git clone --recurse-submodules https://github.com/sipeed/SLogic.git SLogic
cd SLogic
./build/scripts/doctor
```

In an existing checkout, fetch or update the pinned sources with:

```sh
git submodule update --init --recursive
```

The resulting workspace is:

```text
SLogic/
├── artifact/            versioned deliverables (build output, untracked)
├── build/               build system, docs and regression tools
├── slogic/              libslogic: shared SLogic USB/capture core
├── tools/ota/           web firmware update + firmware version table (submodule: sipeed/slogic_ota_server)
└── sources/             pinned submodules
    ├── libsigrok/       Sipeed fork (sipeed-slogic-analyzer driver)
    ├── libsigrokdecode/ upstream
    ├── pulseview/       classic UI
    ├── slogicview/      Sipeed new UI (branch of the same pulseview fork)
    ├── sigrok-cli/      upstream
    ├── all-logic/       AllLogic (DSView-based)
    └── scopehal-apps/   ngscopeclient (with the scopehal library)
```

`slogic/` is the single source of the device logic; `build/scripts/vendor-slogic
sync` copies it byte-identically into libsigrok, all-logic and scopehal, and
`vendor-slogic check` verifies the copies. Fix device behaviour there first.

### Build

```sh
./build/scripts/build --target all
```

On Linux, `all` builds Linux musl and Windows UCRT concurrently. On Apple
Silicon macOS, it builds the native macOS target.

### Versions

- An exact annotated tag `release-X.Y.Z` identifies an immutable release
  source and build combination.
- An untagged workspace commit identifies
  `dev-nightly/<12-character-workspace-commit>`.

Advance a component by moving its submodule to a new commit, then commit the
gitlink change in the workspace:

```sh
git -C sources/libsigrok fetch origin
git -C sources/libsigrok checkout <full-commit>
git add sources/libsigrok
git commit
```

Never move an existing release tag. See `VERSIONING.md` and
`build/docs/release-process.md` for the full policy. Release notes are the
version's section of `CHANGELOG.md`, published to the GitHub release by CI.
