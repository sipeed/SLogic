# Compatibility and dependency audit

## Support status

| Host | Wrapper logic | Released SLogic binary | Hardware capture |
|---|---|---|---|
| Linux x86_64 | Tested | AppImage tested | Previously exercised with SLogicCombo8 |
| Windows | Unit-tested path, `.exe`, environment, and portable-directory handling | Pending Windows release | Pending Windows binary and USB-driver validation |
| macOS | Unit-tested native executable, `.app`, DMG error, and library-path handling | Pending macOS release | Pending macOS binary, signing, and USB validation |

“Unit-tested” verifies the platform-specific Python logic without claiming that an unavailable operating-system binary or USB stack has been exercised.

## Dependency layers

### Plugin host

- A Codex or ChatGPT surface that supports OpenAI plugins and bundled skills.
- No MCP server, network service, or authentication provider is required.

### Wrapper

- Python 3.10 or newer.
- Python standard library only: `os`, `pathlib`, `shutil`, `subprocess`, and `sys`.
- Permission to start the selected executable and to read/write the requested waveform files.

### sigrok distribution

The released binary or portable package must provide a mutually compatible set of:

- `sigrok-cli`;
- libsigrok with the SLogic device driver;
- libsigrokdecode and the required decoder modules;
- the Python runtime used internally by libsigrokdecode;
- libusb and any other dynamic libraries linked by that build.

The wrapper's Python interpreter and libsigrokdecode's embedded Python runtime are separate dependencies. A working `slogic.py -- --version` does not prove that protocol decoding is packaged correctly; release validation must run `slogic.py -- --protocol-decoders uart --show` and decode a known `.sr` file.

### USB capture

- Linux: suitable udev permissions and AppImage runtime support. Systems without FUSE may need an extracted AppImage or a native binary.
- Windows: a compatible USB driver for the SLogic device and all required DLLs from the portable distribution.
- macOS: a signed/notarized binary when required by Gatekeeper, plus libraries inside the app bundle or installation. The user mounts the DMG before selecting the `.app` or executable.

USB access is not required for `decoder-show` or decoding an existing `.sr` file.

## Release acceptance checklist

Run this checklist for every Linux AppImage, Windows portable package, and macOS DMG before marking that host as validated:

1. Start the platform's Python launcher and run `slogic.py` with no arguments; confirm it prints usage.
2. Run `slogic.py --sigrok-cli <path> -- --version` and record the libsigrok/libsigrokdecode versions.
3. Run `slogic.py -- --protocol-decoders uart --show`; confirm decoder modules and the embedded Python runtime load.
4. Decode the known UART `.sr` fixture (`slogic.py -- -i <fixture>.sr -P uart:rx=D0:baudrate=115200 -A uart`) and compare all 90 annotation lines with the reference output.
5. Run `slogic.py -- --driver sipeed-slogic-analyzer --scan` without elevated privileges.
6. Run `slogic.py -- --driver '<scan-spec>' --show` against the selected device.
7. Capture a bounded 50 ms or 500000-sample waveform into a new working directory (`slogic.py -- --driver '<scan-spec>' --samples 500000 -o cap.sr -O srzip`).
8. Open or decode the captured `.sr` file and confirm the output path contains no shell-quoting or Unicode-path corruption.
9. Repeat steps 2–4 from a directory whose path contains spaces and non-ASCII characters.
10. Record packaging-specific failures: missing DLL/dylib, Gatekeeper/quarantine, FUSE, USB driver, udev, or decoder search path.

GTKWave, PulseView, pyserial, and an MCP client are optional companion tools, not runtime dependencies of this plugin.
