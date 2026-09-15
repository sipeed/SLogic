# Architecture

The SLogic workspace is a git superproject that binds product sources and
build logic into a single reproducible workspace revision.

```text
SLogic/
├── artifact/                     final versioned deliverables (untracked)
│   └── <version>/                per-target packages, sources.lock.json, upload/
├── build/                        build system, tracked in the superproject
│   ├── components.toml           libraries and user-facing products
│   ├── environments/             reusable toolchain definitions
│   ├── targets/                  target ABI and packaging drivers
│   ├── common/                   shared compilation support
│   ├── scripts/                  declaration-driven orchestration
│   └── out/                      intermediates (untracked)
│       ├── cache/                downloads and per-target ccache data
│       └── <target>/             persistent target build prefixes
└── sources/                      submodules pinned by full commit
    ├── libsigrok/                Sipeed fork
    ├── libsigrokdecode/          upstream
    ├── pulseview/                classic UI at the 1.0.0 revision
    ├── slogicview/               Sipeed new UI frontend
    └── sigrok-cli/               upstream
```

The workspace commit pins the build system directly and all five source
checkouts as submodule gitlinks. It therefore defines both the source
combination and the exact build/package implementation.

## Version model

- An exact workspace tag `release-X.Y.Z` produces version `release-X.Y.Z`,
  uses `Release`, and embeds `X.Y.Z` where a platform requires an application
  version.
- Any untagged workspace commit produces `dev-nightly/<12-char-commit>` and
  uses `Debug` by default.

Every target records the exported `sources.lock.json`, workspace commit,
source commits, selected products, build host, artifact hashes, target and
build type.

## Three declaration layers

An environment describes only how to obtain a compiler and SDK. Linux and
Windows environments are immutable Docker-compatible images tagged by a hash
of their complete environment directory. A changed Dockerfile creates a new
image; an unchanged one is reused. Containers remain disposable, while the
expensive state is kept in mounted `out/cache` and per-target `out/<target>`
directories.

A target describes an output ABI and package format, selects an environment,
and owns platform-specific compilation and packaging. Current targets are:

- `linux-x86_64-musl`: Alpine container, musl AppImages for PulseView,
  SLogicView and sigrok-cli.
- `windows-x86_64-ucrt`: MSYS2 UCRT64 container, native single-file PulseView,
  SLogicView and sigrok-cli executables with no MSYS runtime dependency. The sigrok-cli
  launcher preserves its command line and console streams while extracting the
  bundled runtime into a content-addressed cache.
- `macos-arm64`: native Apple Silicon build, separate PulseView and SLogicView
  DMGs plus a portable sigrok-cli archive. Each GUI has its own Bundle ID;
  signing and notarization remain environment-controlled steps
  (`MACOS_SIGN_IDENTITY`, `MACOS_NOTARY_PROFILE`). Distributable macOS builds
  must set `SLOGIC_MACOS_PREFIX` to a dependency prefix compiled for the
  advertised `MACOSX_DEPLOYMENT_TARGET` (default 15.0); the conventional
  location is `work/macos15-env` inside the workspace (`work/` is untracked,
  machine-local, and must not be moved — prefix tools bake absolute paths).
  Building against Homebrew instead bundles libraries compiled for the
  host's own macOS version, and the bundle validation step fails with
  "Deployment target mismatch" — expected, not a build bug.

`components.toml` declares every component: its source checkout, its
dependencies, supported targets and whether it is a reusable library or a
user-facing product. `libsigrok` and `libsigrokdecode` are shared components;
`pulseview`, `slogicview` and `sigrok-cli` are products. Adding ngscopeclient
or bridge starts with a new component declaration and then adds the required
platform hooks to each target that supports it.

## Scheduling and reuse

`scripts/build` discovers declarations, computes dependency closure and gives
all concurrent work one total `--jobs` budget. If two targets run together,
the budget is divided between targets; each target divides its share between
changed products. This prevents a nominal 64-job build from becoming 128 or
256 competing compiler processes.

Within a target, shared sigrok libraries are built once and installed into its
persistent prefix. Revision and target-specific build-logic stamps decide which
dependency or product must be invalidated, so changing a Linux packager does
not discard Windows intermediates. Linux and Windows identical reruns reuse the
environment image, prefix, product build and existing package. ccache remains
a secondary safety net for partial rebuilds after source changes. The macOS
target persists intermediates too.

Uncommitted edits under `sources/` are first-class for nightly builds: the
host records each source as `<commit>` or `<commit>-dirty`, and a dirty
source always re-runs make incrementally without discarding the persistent
work tree. Dirty states are recorded in `sources.lock.json` and
`build-info.json`, so a dev artifact is never mistaken for a pure pinned
build. Release builds still require clean checkouts. It prepares one dependency closure for both
GUI bundles and the CLI, then gives PulseView and SLogicView independent app
identities, signatures and disk images.

Useful controls:

```sh
./build/scripts/build --list
./build/scripts/build --target all --product all --jobs 64
./build/scripts/build --target linux-x86_64-musl --product sigrok-cli
./build/scripts/build --target windows-x86_64-ucrt --clean
./build/scripts/build --target linux-x86_64-musl --rebuild-environment
```

Linux and Windows can build concurrently on a Linux host. macOS must build on
an Apple Silicon host; its target directory can then be synchronized into the
same version directory before running `scripts/package-release`.
