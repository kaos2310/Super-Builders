# SukiSU41013 scoped-session compatibility

Baseline: successful Super-Builders run 39061619013 at
9b9f7853cc167f3f0bf4528824fe4ecd1bc7d704 (SukiSU41007, EZIF/EUX).
The target is official SukiSU Ultra ffa00c0700604216de8a86ad9c74226af1add0d5:
40000 + 3828 commits - 2815 = 41013, release family v4.2.1.

This is a fork migration. SukiSU's native UAPI6 headers, userspace,
manager identity and scoped driver remain native to that exact source pin.
The expected manager package is com.sukisu.ultra; a BakaSU manager is not
the paired manager for this target.

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

The separate ../sukisu-41013-susfs/ port retains SukiSU's byte-identical
native SELinux implementation and requires matched independent evidence.
Final CI verifies exact source hashes, embedded configuration, stock Samsung
module CRCs, Image identity, unique compiled functions and package attestations.
Those checks remain required before a flash ZIP exists.

SukiSU41013's optional native preinit runner is disabled in this bounded
SUSFS manual-hook profile because it requires the native syscall dispatcher.
The UAPI6 header remains unchanged; the compiled PREINIT feature flag is false.
CPU/PID limits and KPM are disabled, preserving the chosen baseline profile.
Physical-device installation, boot, Manager pairing and runtime are untested.

SukiSU41013 mount_hide keeps its native UID/feature behavior. The bounded port
adds separate wrappers for all three SUSFS show callbacks so per-file original
callbacks never leak between native and SUSFS views. Exact callback/filter host
tests cover SUSFS on/off, three negative controls and the actual proc_mounts
prefix. Proc namespace and the full SukiSU subtree compile for ARM64.
