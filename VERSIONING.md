# Versioning policy

The workspace commit is the SLogic aggregate version. It pins:

- the build system, tracked directly in `build/`;
- the Sipeed libsigrok fork;
- classic PulseView and new SLogicView revisions from the Sipeed fork;
- upstream libsigrokdecode;
- upstream sigrok-cli.

Development builds use `dev-nightly/<workspace-commit>`. A tested workspace
commit becomes a release only when tagged `release-X.Y.Z`. Release tags must
never be retargeted.

Source revisions are recorded as submodule gitlinks, always full commits.
Every pinned commit must stay reachable from a branch or tag in its remote
repository; never rewrite or delete a remote branch that a release pin
depends on.

The `sources.lock.json` exported during each build is shipped with the
output, so a release remains reconstructible even if remote default branches
advance.
