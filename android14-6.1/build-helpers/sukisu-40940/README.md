# SukiSU 40940 for S928BXXU6ZZI4/EUX

Checked 2026-09-30. Native SUSFS kernel source is the current `builtin` head
`b20dee702035af09cb2ecb5f35443bbc1747f3e6`, version v4.2.0. Upstream's builtin
Makefile derives its manager version from `main`, whose immutable current head
`7fbbb1f12e2410b69c8ebf958be84f165b8d0c93` has 3755 commits:
`40000 + 3755 - 2815 = 40940`. Both references are recorded separately.

The ZZI4 pipeline retains source and firmware identity, strict Samsung DLKM CRC
checks, Gunyah changes, SUSFS 2.3.0, ZeroMount, UIDGate, OPEN_REDIRECT,
bootconfig static-key fix and final package audits from run 36634254677.

SukiSU builtin uses a boolean `ksu_su_compat_enabled` and the native
`[ksu_driver]` manager ABI. The bounded adapter verifies all source anchors
before writing and bridges the generic SUSFS hooks to that native ABI. It
carries the reference su-session behavior: root-profile and ucounts failures
propagate, a failed privilege transition leaves the su path unchanged, and
only a successful su exec installs the native driver FD after exec.

The WebView UID 1053 remains a non-root persisted profile after allowlist
pruning, including in the zygote_next path. Exact-C tests execute the native
session, WebView policy and SUSFS KSTAT code; mutation checks reject FD
installation after failed or ordinary exec and ignored root-profile errors.
VFS scope/order, UIDGate and Gunyah checks remain mandatory CI gates.

Package attestation requires final config, compiled version and driver strings,
compiled executable SUSFS/root-hook definitions, firmware/KMI checks and a
reject-free build. A CI artifact does not prove live device behavior.
