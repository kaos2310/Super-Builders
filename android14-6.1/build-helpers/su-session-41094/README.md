# SukiSU41094 scoped-session compatibility

Baseline: successful Super-Builders run 39293074011 at
cc8b170ab3f85310359a14bb0dc0effc2e059cf8 (SukiSU41027, EZIF/EUX).
The target is official SukiSU Ultra 2ec445ffcb803614ee41ce111b6bad28c67f3347:
40000 + 3909 commits - 2815 = 41094, release family v4.2.1-r2.

This is a pinned upstream update. SukiSU's native UAPI6 headers, userspace,
manager identity and scoped driver remain native to that exact source pin.
The expected manager package is com.sukisu.ultra; a BakaSU manager is not
the paired manager for this target.

The native 41094 extension ioctl is kept with its matching userspace and
all six native handlers. Extension lifecycle and forced-state replay are
retained in the manual built-in boot path and tested separately.

The SUSFS 2.3.0 manual-hook profile retains the previous explicit session
decision and post-success FD installation. The compatibility patch uses
the validated manual sucompat C/header from BakaSU 2489b385, adapts its
logging/boot calls to SukiSU's native interfaces, and preserves the ksud
existence check before committing root credentials. Native SukiSU setuid
handling is retained with the official SUSFS patch and a bounded WebView
profile guard. SukiSU already preserves WebView during allowlist pruning.

apply.py accepts only the exact SukiSU/SUSFS pair, validates immutable
UAPI6 and userspace sources, and plans all source substitutions before writes.
test.py compiles the actual generated C and tests exec/session scope,
credential errors, missing ksud, stale flags, ioctl permissions, KSTAT layout
and WebView policy, including eighteen negative controls. Kernel API mocks
are used; these are not device or concurrency tests.
The WebView harness also exercises native RCU unmount-policy lookups,
manager exemptions across users and mismatched hash-bucket UIDs.

The separate ../sukisu-41094-susfs/ port retains SukiSU's byte-identical
native SELinux implementation and requires matched independent evidence.
Final CI verifies exact source hashes, embedded configuration, stock Samsung
module CRCs, Image identity, unique compiled functions and package attestations.
Those checks remain required before a flash ZIP exists.

SukiSU41094's optional native preinit runner is disabled in this bounded
SUSFS manual-hook profile because it requires the native syscall dispatcher.
The UAPI6 header remains unchanged; the compiled PREINIT feature flag is false.
CPU/PID limits remain disabled. This branch enables native KPM with the paired
source-built KernelPatch engine; see ../sukisu-kpm/README.md and its Image audit.
Physical-device installation, boot, Manager pairing and runtime are untested.

SukiSU41094 mount_hide keeps its native UID/feature behavior. The bounded port
adds separate wrappers for all three SUSFS show callbacks so per-file original
callbacks never leak between native and SUSFS views. Exact callback/filter host
tests cover SUSFS on/off, three negative controls and the actual proc_mounts
prefix. Proc namespace and the full SukiSU subtree compile for ARM64.
