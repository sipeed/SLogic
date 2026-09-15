# Release process

1. Advance submodule pins in the workspace and commit the change.
2. Sync a clean checkout: `git pull && git submodule update --init --recursive`.
3. Build all products from the untagged workspace commit as
   `dev-nightly/<commit>` on Linux and macOS.
4. Verify the artifacts and exported `sources.lock.json`.
5. Tag the already-tested workspace commit as `release-X.Y.Z`.
6. Check out the release tag, re-sync submodules, and build Release artifacts
   on both hosts.
7. Gather all target directories under `artifact/release-X.Y.Z/`.
8. Run `./build/scripts/package-release release-X.Y.Z`.

For SLogic 1.1.0 and later, each platform ZIP is complete only when it contains
the classic PulseView frontend, the new SLogicView frontend, and sigrok-cli.
Public archive names remain `SLogic-X.Y.Z-<platform>.zip`; ABI details such as
`musl` and `ucrt` remain visible in artifact names and build metadata.

Environment images, target workspaces and ccache may be reused between nightly
and release validation. The exported source lock and clean-checkout
requirement, not an empty build directory, define release reproducibility. Use
`--clean` when validating a toolchain or investigating incremental-build
differences.

Never move an existing release tag. A new source or build combination requires
a new version tag. Pinned submodule commits must stay reachable from a branch
or tag in their remote repository; never rewrite or delete a branch that a
release pin depends on.
