# SLogic build system

This directory is the build system of the SLogic superproject. Product
sources are sibling submodules under `sources/` and are never cloned by the
build scripts.

```text
SLogic/
├── build/
└── sources/
    ├── libsigrok/
    ├── libsigrokdecode/
    ├── pulseview/       # classic UI
    ├── slogicview/      # Sipeed new UI
    └── sigrok-cli/
```

Build every target supported by the current host:

```sh
./build/scripts/doctor
./build/scripts/build --target all
```

Build selected products for one target:

```sh
./build/scripts/build --target linux-x86_64-musl --product pulseview
./build/scripts/build --target windows-x86_64-ucrt --product pulseview,slogicview,sigrok-cli
./build/scripts/build --target macos-arm64
```

The job count is one total CPU budget, even when targets or products run in
parallel:

```sh
./build/scripts/build --target all --jobs "$(nproc)"
```

Build environments are immutable content-addressed images. Target workspaces,
download caches and ccache data persist under `out/`, so ordinary reruns are
incremental. Editing files under `sources/` without committing and re-running
the build produces a `dev-nightly` artifact containing those edits; only the
affected objects are recompiled. Use `--clean` to discard selected target
intermediates or `--rebuild-environment` to deliberately rebuild its
toolchain image.

An exact workspace tag named `release-X.Y.Z` selects a Release build and
embeds `X.Y.Z` into platform metadata. Any untagged workspace commit produces
a Debug build under `artifact/dev-nightly/<workspace-commit>/`.

SLogic 1.1.0 and later release packages contain three user-facing products:
PulseView with the classic UI, SLogicView with Sipeed's new UI, and sigrok-cli.
The two GUIs use independent application identities and settings stores while
remaining compatible with sigrok session files.

See [docs/architecture.md](docs/architecture.md) for the complete workflow.
