# sigrok-cli SLogic plugin

`sigrok-cli-slogic-plugin` is a skill-only OpenAI plugin for bounded waveform capture and protocol decoding through `sigrok-cli`. It does not bundle an MCP server or a `sigrok-cli` binary.

## Runtime dependencies

- Python 3.10 or newer. The plugin uses only the Python standard library.
- A SLogic-enabled `sigrok-cli` executable with matching libsigrok, libsigrokdecode, protocol decoders, and device drivers.
- USB access to the logic analyzer for capture. Decoding an existing `.sr` file does not require hardware.

Set `SIGROK_CLI` or pass `--sigrok-cli` when the executable is not on `PATH`.

## Supported host forms

| Host | Accepted binary form | Additional runtime requirements |
|---|---|---|
| Linux | Native `sigrok-cli` or executable AppImage | AppImage runtime support; udev/libusb permission for capture |
| Windows | `sigrok-cli.exe` or its extracted portable directory | Matching DLLs beside the executable or under the portable distribution; compatible USB driver |
| macOS | Native `sigrok-cli`, mounted `.app`, or executable inside `Contents/MacOS` | Signed/notarized binary as required by the host; matching libraries in the app bundle or installation |

A `.zip` or `.dmg` is a distribution container, not an executable. Extract a Windows archive first. Mount a macOS DMG, then pass the `.app` bundle or its `Contents/MacOS/sigrok-cli` executable.

## Validation

```bash
python3 -m unittest discover -s tests -v
python3 skills/sigrok-cli-slogic/scripts/slogic.py                # prints wrapper usage
python3 skills/sigrok-cli-slogic/scripts/slogic.py -- --version   # forwards to sigrok-cli
```

Hardware-independent tests cover Linux executability, Windows `.exe` and portable-directory discovery, macOS `.app` discovery, DMG rejection, and platform-specific dynamic-library search paths. Hardware capture still requires validation on each released binary and USB stack.
