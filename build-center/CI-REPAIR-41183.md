# SukiSU 41183 source compatibility

The official main branch advanced while the repair of run 43610196412 was
being tested. The app correctly rejected submitting the stale reviewed
41181 source pair. The replacement candidate is frozen to SukiSU commit
`ef77212e51c95886192ac066ec7ec28a0108cdee` (3998 commits, version 41183)
and SuSFS v2.4.0 commit `f76b81f2a6bf98e4029cc0c823c054edbec29803`.

SukiSU changes since 41181 add a native inode_setxattr SELinux handler and
userspace lint fixes. The kernel/Kbuild blob is byte-identical to 41181:
`029f391165b27c59cebacc91e94842c2fccdac8e`. The existing exact compatibility
fragment is therefore mapped to 41183 without changing its output. The
original native SELinux implementation is retained and verified against
the pinned upstream source in CI. No manual SuSFS SELinux hook is restored.

The SuSFS changes since e6dc76f5 affect the readdir include guards and the
legacy manual SELinux handler. Replaying the full a2165b6f to f76b81f2 delta
on the actual pinned Samsung/AOSP reference files passed. The native
SELinux exclusions and strict conflict checks remain in place.

This change is source preparation. A successful full ARM64 kernel build,
strict KMI and stock module CRC checks, and artifact attestations must all
come from the subsequent CI run. No boot or flash test is claimed.
