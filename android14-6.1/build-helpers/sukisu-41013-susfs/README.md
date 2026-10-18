# S928B EZIF / SukiSU41013 / SUSFS 2.3.0

This port starts from successful run 39061619013, commit
9b9f7853cc167f3f0bf4528824fe4ecd1bc7d704. The firmware target remains
SM-S928B / S928BXXU6EZIF / EUX, Linux 6.1.162 with full-strict KMI.

Official SukiSU source: ffa00c0700604216de8a86ad9c74226af1add0d5, version
41013 from 40000 + 3828 - 2815. Kernel and ARM64 userspace use the same pin.
SUSFS remains the baseline's android14-6.1 pin
5369359dbd10f6dd8cbdd59d1df7b788b29b168c, v2.3.0.

compat.patch is an exact downstream port of SUSFS's official KernelSU patch.
Release applies it with git apply --check on the exact SukiSU source,
without fuzzy patching. Native SukiSU SELinux, UAPI6 headers, userspace,
manager authentication and new symbol-lookup interfaces are retained.
Only the two parallel manual common-tree SELinux sections are reversed;
SUSFS AVC logging and filesystem features remain present.

The manual sucompat C/header and SUSFS command dispatcher are derived from
the proven BakaSU35231 source 2489b385, with bounded wrappers for SukiSU's
native boot, logging and adb-root signatures. The session adapter, UIDGate,
Enhanced SUSFS, dual-layout ZeroMount bridge, OPEN_REDIRECT and previous
Samsung/Gunyah/DroidSpaces changes remain present. SukiSU's own native
setuid/manager handling is used; BakaSU's multi-manager-only config symbol
is not asserted for this different implementation.

SukiSU's new optional preinit runner requires its native syscall dispatcher.
This manual-hook profile compiles it out using the existing KSU_NO_PREINIT
contract, so it advertises PREINIT=false. UAPI6 and LOOKUP_SYMBOLS remain
unchanged. KPM and CPU/PID resource limits remain off in this baseline profile.
Native SELinux symbol resolution requires KALLSYMS_ALL=y.

The apply.py gate requires a matching source pin, kernel-patch hash,
compatibility-patch hash, port/session-helper hashes and independent test
results before making any writes. check.py compares all effective kernel and UAPI sources with the locally compiled/replayed source hashes
after downstream transforms and before packaging.

Independent local verification covers 42 ARM64 objects, a combined
relocatable SukiSU object with no unresolved internal ksu_ symbols, native
SELinux/exec compilation, fresh patch replay, eighteen session negative
controls, six service-event negative controls, bindings/OUT_DIR tests,
and rejection of missing or invalid port evidence. The local compile uses
LTO_NONE. Full kernel linking, CI's LTO/CFI mode, strict stock module CRCs,
embedded config and flash-package checks remain mandatory CI gates.
No device installation, boot or runtime test has been performed.

SukiSU uses one workspace Cargo.lock. The exact lock helper changes
only three dangling bitflags dependency edges in kqueue-sys, notify and
redox_syscall to the version already locked upstream (2.13.2). It changes
no package versions or checksums. Both real Android metadata graphs pass
--locked with 222 resolved nodes and unchanged effective lock bytes.

SukiSU41013 mount_hide keeps its native UID/feature behavior. The bounded port
adds separate wrappers for all three SUSFS show callbacks so per-file original
callbacks never leak between native and SUSFS views. Exact callback/filter host
tests cover SUSFS on/off, three negative controls and the actual proc_mounts
prefix. Proc namespace and the full SukiSU subtree compile for ARM64.
