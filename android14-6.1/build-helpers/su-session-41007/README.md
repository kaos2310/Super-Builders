# SukiSU41007 scoped-session compatibility

Baseline: successful Super-Builders run 39047475246 at
8ba69d1340eed4e210849719ec00fe1f47e2062d (BakaSU35231, EZIF/EUX).
The target is official SukiSU Ultra f6731caa0e0bee7787653334b2930ed041938ef6:
40000 + 3822 commits - 2815 = 41007, release family v4.2.1.

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

The separate ../sukisu-41007-susfs/ port retains SukiSU's byte-identical
native SELinux implementation and requires matched independent evidence.
Final CI verifies exact source hashes, embedded configuration, stock Samsung
module CRCs, Image identity, unique compiled functions and package attestations.
Those checks remain required before a flash ZIP exists.

SukiSU41007's optional native preinit runner is disabled in this bounded
SUSFS manual-hook profile because it requires the native syscall dispatcher.
The UAPI6 header remains unchanged; the compiled PREINIT feature flag is false.
CPU/PID limits and KPM are disabled, preserving the chosen baseline profile.
Physical-device installation, boot, Manager pairing and runtime are untested.
