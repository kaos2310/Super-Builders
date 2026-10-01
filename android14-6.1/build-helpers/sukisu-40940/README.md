# SukiSU 40940 UAPI4 for S928BXXU6ZZI4/EUX

Checked 2026-09-30. Native SUSFS kernel source is the current `builtin` head
`b20dee702035af09cb2ecb5f35443bbc1747f3e6`, version v4.2.0. Upstream's builtin
Makefile derives its manager version from `main`, whose immutable current head
`7fbbb1f12e2410b69c8ebf958be84f165b8d0c93` has 3755 commits:
`40000 + 3755 - 2815 = 40940`. Both references are recorded separately.

The ZZI4 pipeline retains source and firmware identity, strict Samsung DLKM CRC
checks, Gunyah changes, SUSFS 2.3.0, ZeroMount, UIDGate, OPEN_REDIRECT,
bootconfig static-key fix and final package audits from run 36634254677.

Upstream builtin exposes UAPI2 while the current 40940 manager expects UAPI4.
The bounded `uapi4.py` adapter ports the real driver context and ioctl permission
contract from the immutable main reference above. It retains `[ksu_driver]` for
the manager and installs `[ksu_driver_su]` only after a successful su exec.
Only GET_WRAPPER_FD and DISABLE_ESCAPE_TO_ROOT receive scoped-session permission;
the ordinary manager/root/allowlist checks remain active for every other ioctl.
GET_INFO reports UAPI4 and correct built-in flags (BUNDLED and LATE_LOAD clear).
The wrapper inode is created with KernelSU credentials, as in the immutable
main source, and the caller's credentials are restored before publishing the
file. This preserves terminal wrappers with restricted root-profile domains;
allocation and inode-creation failures also restore credentials and release
the reserved FD and references.
Existing profile/event/SELinux payloads and ioctl numbers are compared against
the manager's source. The SUSFS-integrated builtin hooks remain in use.

The bounded adapter verifies all source anchors before writing. It
carries the reference su-session behavior: root-profile and ucounts failures
propagate, a failed privilege transition leaves the su path unchanged, and
only a successful su exec installs the native driver FD after exec. A blocked
privilege transition cannot create a session. Missing ksud retains the native
reference shell fallback without installing an extra FD.

The WebView UID 1053 remains a non-root persisted profile after allowlist
pruning, including in the zygote_next path. Exact-C tests execute the driver,
permission dispatcher, GET_INFO, native session, wrapper cleanup, WebView policy
and SUSFS KSTAT code; mutation checks reject FD
installation after failed or ordinary exec, ignored root-profile errors,
unscoped ioctl permission bypasses and unbalanced wrapper credentials.
VFS scope/order, UIDGate and Gunyah checks remain mandatory CI gates.
The compiled UAPI value used by GET_INFO is read independently from the ARM64
vmlinux symbol `ksu_uapi4_contract`; both driver names and the scoped installation
function must exist in the package Image/compiled kernel. Package and workflow
identities include UAPI4 so these builds can be distinguished from UAPI2 builds.

Package attestation requires final config, compiled version and driver strings,
compiled executable SUSFS/root-hook definitions, firmware/KMI checks and a
reject-free build. A CI artifact does not prove live device behavior.
