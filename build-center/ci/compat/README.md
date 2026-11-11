# SukiSU 41176 Kbuild compatibility refresh

The baseline builder `f269b2d31779901efe920c3c8a3f00838e35e119` carries the
audited SukiSU 41165 compatibility patch. Upstream commit
`3af6085d0d26e73ffd1a3e7b34362435dcfb5a03` (41176, 3991 commits) contains
additional preinit runner linker flags. The old deletion hunk consequently
fails at `kernel/Kbuild:128`.

`kbuild-41176.patch` refreshes only that file's diff section against the exact
official 41176 preimage. Before version-specific identity assignments are
configured, the resulting canonical LF Kbuild is byte-identical to the
baseline compatibility profile: SHA-256
`20328dc418d2bcadf181e8ce4cccf078ce4b140b733274c64b8b70e2774aadb5`.

`ci/kbuild_compat.py` selects this refresh only for the exact 41176 source pin
and verifies the known baseline and replacement fragment hashes. Every other
compatibility-patch section is retained byte-for-byte. Missing, duplicated or
changed Kbuild templates fail. Other upstream pins are not automatically
rebased. The existing complete `git apply --check`, source identity, semantic,
kernel build and strict CRC gates still execute.

The baseline regression fixture was copied from
`android14-6.1/build-helpers/sukisu-41165-susfs/compat.patch` at the above pinned
builder commit. Local integration verification used the real baseline builder,
the official full-history 41176 worktree and the real migrated configuration
helper. It is source-preparation evidence; compilation and device-runtime
evidence are separate.
