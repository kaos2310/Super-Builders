# SM-S928B EZIF with SukiSU 41165

This profile extends commit 4369dc1 on Linux 6.1.162 for S928BXXU6EZIF / EUX.
Official SukiSU 41165 is pinned to d7d042816b82b200c25b3a93dcc158ba0307cabf.
Its version calculation is 40000 + 3980 - 2815 = 41165.
The verified official ARM64 Manager comes from the manager-ci channel.
Native original-type metadata and policy sequence handling introduced in 41152
are preserved and freshly compiled with the SukiSU ARM64 object subtree.
UAPI, userspace and Cargo.lock match 41150.

The official SuSFS gki-android14-6.1 head was fetched on 2026-11-06.
It reports v2.3.0 at 5f85e6e7838a54ad363de5749d33361a5da2316b.
The seven priority functions match this current official source byte for byte.
Integration uses the audited 5369359d base with the current priority, parser,
Kconfig and feature overlay plus native SukiSU SELinux.
The latest upstream manual SELinux patch replaces the original-type helpers.
That alternative implementation and logging-only changes to its absent manual
functions are outside this native SELinux profile.
See UPSTREAM-VERIFICATION.json and ../susfs-priority-uid-41165/SOURCE.json.

All 15 supported SuSFS Kconfig options are enabled in the effective profile.
All 14 child features are advertised to userspace.
The HIDDEN_NAME advertisement is added, and the unused HARDENED toggle is
removed because the existing code fixes are unconditional.
The build audit rejects missing features, disabled required options and
unknown active settings. It runs on both source and final configuration paths.
See SUSFS-SETTINGS.json and ../audit-susfs-41165.py.

Fresh checks cover 57 ARM64 objects, replay of 197 kernel/UAPI sources,
55 daily configuration checks, both locked Android Cargo graphs, session
faults, UAPI services, extension ABI 2, priority parser, UIDGate, Gunyah,
KPM bridge ABI 2, Image recovery controls and package tests.
The Image transformation fixture uses a historical Linux 6.1.162 Image.
The full 41165 kernel link, Samsung stock-module CRC/KMI, complete Android
userspace compilation and physical boot are pending.
