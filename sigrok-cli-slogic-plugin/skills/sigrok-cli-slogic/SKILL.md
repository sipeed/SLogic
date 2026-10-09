---
name: sigrok-cli-slogic
description: Thin cross-platform forwarder to a SLogic-capable sigrok-cli. Use it to discover connected SLogic/DSLogic logic analyzers, inspect a device's channels / sample rates / config, run bounded captures (channels, sample rate, voltage threshold, triggers), and decode protocols from saved .sr waveforms. The wrapper only locates the binary and fixes its library path; every option is native sigrok-cli syntax discovered from the binary itself via `--help`, `-L`, and `--show`.
---

# SLogic capture and decode via sigrok-cli

`scripts/slogic.py` is a **thin forwarder**: it finds the SLogic-capable `sigrok-cli`
across Linux/macOS/Windows, adds its bundled libraries to the dynamic-linker path, and
passes every other argument straight through. It encodes no options of its own — the
authoritative option reference is the binary, via `--help`, `-L`, and `--show`.

Run it from the user's working directory; do not `cd` into the skill directory.

```bash
python3 /path/to/skill/scripts/slogic.py [--sigrok-cli PATH] -- <sigrok-cli args...>
```

- Binary selection: `--sigrok-cli PATH` (first argument), else `$SIGROK_CLI`, else `sigrok-cli`
  in the current directory, else on `PATH`. An explicit PATH may be a native executable, a
  Windows portable directory containing `bin/sigrok-cli(.exe)`, or a mounted macOS `.app`.
  A `.zip`/`.dmg` is a container, not an executable — extract/mount it first.
- The optional `--` separates the wrapper's `--sigrok-cli` selector from forwarded args. Anything
  after it (including `--help`) goes to sigrok-cli unchanged.
- Use the platform Python launcher: `python3` on Linux/macOS, `py -3` or `python` on Windows.
  Python 3.10+; standard library only.

## Discover before acting — never guess options

Read capabilities from the binary instead of assuming them:

```bash
python3 .../slogic.py -- --version                                  # libsigrok/decode versions
python3 .../slogic.py -- -L                                         # drivers and decoders present
python3 .../slogic.py -- --driver sipeed-slogic-analyzer --scan     # find the device
python3 .../slogic.py -- --driver '<scan-spec>' --show              # rates, channels, config keys
python3 .../slogic.py -- --protocol-decoders uart --show            # decoder pins/options
```

Workflow: `--scan` first and report matches (don't acquire if none); if several match, ask which
`conn` spec to use; `--show` when you need exact rates/channels/keys; then capture; then decode.

## Capture — always bounded

sigrok-cli runs forever without a limit, so always pass `--samples N` or `--time <ms>`. Save with
`-o <file> -O srzip`. SLogic (`sipeed-slogic-analyzer`) device knobs go through `--config`:

```bash
python3 .../slogic.py -- --driver sipeed-slogic-analyzer \
  --config logic_channels=16:samplerate=10m:voltage_threshold=1.7-1.7:pattern=Normal \
  --channels D0-D15 --triggers D0=r --samples 1000000 -o capture.sr -O srzip
```

Accuracy notes for the SLogic driver (confirm exact values with `--show`):
- Multiple `--config` settings are separated by **`:`** (colon), not commas, e.g.
  `--config logic_channels=16:samplerate=10m`.
- `logic_channels=N` selects the channel mode and **recomputes the max sample rate**; put it
  **before** `samplerate=` in the same `--config`, as it also enables D0..D(N-1).
- `samplerate` takes SI forms (`200k`, `10m`, `24000000`); an over-limit value is clamped with a warning.
- `voltage_threshold` is a `LOW-HIGH` pair in volts (single switching point → `1.7-1.7`), range 0–6 V.
- `pattern` names come from `--show`.
- Channels are `D0..Dn`; `--channels D0-D7,D9` selects a subset.
- Triggers: `--triggers Dn=COND` with COND one of `0 1 r f e` (comma-separate multiple).

## Decode a saved waveform

No USB needed. Discover pins with `--protocol-decoders <id> --show`, then require an explicit
pin→channel mapping (ask for missing ones; do not assume channel order). Native `-P`/`-A` syntax:

```bash
python3 .../slogic.py -- -i capture.sr -P uart:rx=D0:baudrate=115200 -A uart
python3 .../slogic.py -- -i capture.sr -P i2c:scl=D0:sda=D1 --protocol-decoder-samplenum
python3 .../slogic.py -- -i capture.sr -P spi:clk=D0:mosi=D1:cs=D2:cpol=0:cpha=0
```

Stack higher-level decoders by appending them to `-P`, e.g. `-P i2c:...,eeprom24xx`. Report the
decoder, pin mapping, options, and whether annotations appeared. Treat empty output as "no
annotations under this configuration," not proof the bus is idle.

## Reporting

Echo the exact forwarded command (the wrapper prints it as `+ …` on stderr) and the absolute path
of any `.sr`/output file, so the user can reproduce or adjust the run.
