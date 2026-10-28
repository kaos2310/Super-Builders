# S928B EZIF / SukiSU41098 / SUSFS 2.3.0

This port starts from successful run 40577344297, commit
2b4858bd318aaa340d54973b45f6a02941b63bb5 (SukiSU41096 with KPM), including its tested
ZeroMount installer CLI fix. The firmware target remains
SM-S928B / S928BXXU6EZIF / EUX, Linux 6.1.162 with full-strict KMI.

Official SukiSU source: 29f8b18d08dae3be66c0c3cd364536827df0a378, version
41098 from 40000 + 3913 - 2815, release family v4.2.1-r2 verified on
2026-10-28. Kernel and ARM64 userspace use the same pin.
SUSFS remains the baseline's android14-6.1 pin
5369359dbd10f6dd8cbdd59d1df7b788b29b168c, v2.3.0.

compat.patch is an exact downstream port of SUSFS's official KernelSU patch.
Release applies it with git apply --check on the exact SukiSU source,
without fuzzy patching. Native SukiSU SELinux, UAPI6 headers, userspace,
manager authentication and symbol-lookup interfaces are retained. The native
41098 extension dispatcher, all six extension handlers and the paired userspace
extension sources remain unchanged. The manual built-in lifecycle registers
the handlers before ksud initialization and replays forced extension state at
init's second stage, alongside the existing forced-feature replay.
Only the two parallel manual common-tree SELinux sections are reversed;
SUSFS AVC logging and filesystem features remain present.
The native AVC feature initialization and boot-completed hook are retained.
Native manager signature fallback, version extension and RCU unmount policy
remain upstream-identical. The RCU test mocks were updated for the new API,
including manager, multiuser, missing-profile and UID-collision cases.

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
unchanged. This KPM branch enables KPM with a paired, source-built KernelPatch
engine; CPU/PID resource limits remain off. See ../sukisu-kpm/README.md.
Native SELinux symbol resolution requires KALLSYMS_ALL=y.

The apply.py gate requires a matching source pin, kernel-patch hash,
compatibility-patch hash, port/session-helper hashes and independent test
results before making any writes. check.py compares all effective kernel and UAPI sources with the locally compiled/replayed source hashes
after downstream transforms and before packaging.

Independent local verification for this KPM profile covers 55 ARM64 objects, a combined
relocatable SukiSU object with no unresolved internal ksu_ symbols, native
SELinux/exec compilation, fresh patch replay, eighteen session negative
controls, six service-event negative controls, four extension ABI/dispatch
negative controls, 194 hashed kernel/UAPI sources, bindings/OUT_DIR tests,
and rejection of missing or invalid port evidence. The local compile uses
LTO_NONE. Full kernel linking, CI's LTO/CFI mode, strict stock module CRCs,
embedded config and flash-package checks remain mandatory CI gates.
No device installation, boot or runtime test has been performed.

SukiSU uses one workspace Cargo.lock. The new upstream lock includes dependencies
for temporary-root lease encryption. The lock helper verifies that official
lock without downstream changes to bytes, versions or checksums. Both real
Android metadata graphs pass --locked with 232 resolved nodes and unchanged
effective lock bytes.

SukiSU41098 mount_hide keeps its native UID/feature behavior. The bounded port
adds separate wrappers for all three SUSFS show callbacks so per-file original
callbacks never leak between native and SUSFS views. Exact callback/filter host
tests cover SUSFS on/off, three negative controls and the actual proc_mounts
prefix. Proc namespace and the full SukiSU subtree compile for ARM64.

The native extension ABI is 2, including kernel-driven handler enumeration.
The official priority UID filter and RCU/worker fixes are included; see
../susfs-priority-uid/README.md for source provenance and verification limits.
