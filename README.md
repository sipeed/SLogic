# SLogic

Aggregate workspace for the SLogic software stack. This repository is a git
superproject: the multi-platform build system is tracked directly in `build/`,
and every product source is pinned as a git submodule under `sources/`.

## Get the workspace

```sh
git clone --recurse-submodules git@git.corp.sipeed.com:sipeed_software/slogic.git SLogic
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
├── build/               build system (part of this repository)
└── sources/             pinned submodules
    ├── libsigrok/       Sipeed fork
    ├── libsigrokdecode/ upstream
    ├── pulseview/       classic UI
    ├── slogicview/      Sipeed new UI (branch of the same pulseview fork)
    └── sigrok-cli/      upstream
```

## Build

```sh
./build/scripts/build --target all
```

On Linux, `all` builds Linux musl and Windows UCRT concurrently. On Apple
Silicon macOS, it builds the native macOS target.

## Versions

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
`build/docs/release-process.md` for the full policy.

SLogic 1.1.0 introduces a three-product package: classic PulseView,
SLogicView, and sigrok-cli. PulseView and SLogicView are pinned independently
from the same fork so the familiar UI remains available while the new UI
continues to evolve.
