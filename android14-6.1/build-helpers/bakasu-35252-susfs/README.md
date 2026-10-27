# BakaSU 35252 / SUSFS 2.3.0 / S928B EZIF

Verified upstream on 2026-10-27:
- BakaSU pin: `d5e9e025b8b49155f8014684d64c91742b465f65`.
- Version: 30,700 + 4,552 commits = **35252**; UAPI **6**.
- Builder baseline: successful [run 39047475246](https://github.com/kaos2310/Super-Builders/actions/runs/39047475246), commit `8ba69d1340eed4e210849719ec00fe1f47e2062d`.
- Target stays SM-S928B / S928BXXU6EZIF / EUX, Android 14 KMI / Linux 6.1.162.
- SUSFS stays `5369359dbd10f6dd8cbdd59d1df7b788b29b168c`, version 2.3.0.
- ZeroMount stays `c3cb7ffdf749f2441928ec47798615a4c79fab65`.
- CPU/PID limits stay omitted; memory limits and the existing DroidSpaces feature profile remain.

The upstream delta contains 21 commits since BakaSU 35231. It includes UAPI6
symbol lookup/preinit support, module preinit and hot installation, forced
feature values, shell/ADB restriction, syscall compatibility and module-blacklist
changes. Kernel and ARM64 ksud/ksuinit are rebuilt together.

The previous local native SELinux integration is retained: reverse only the
obsolete SUSFS manual hooks in `security/selinux/hooks.c` and
`security/selinux/selinuxfs.c`. BakaSU's native SELinux source is kept identical
to the new upstream pin. AVC logging, filesystem hooks, UIDGate and ZeroMount
are preserved. The old upstream SUSFS build block was removed upstream;
this adapter never edits or bypasses `kernel/tools/susfs_compat.mk`.

Release application requires the matching independent `PREFLIGHT.json`.
Missing or mismatched evidence is rejected before changes. The evidence records
43 ARM64 object files, including the complete BakaSU object subtree, SELinux and
exec; the ARM64 preinit runner and generated syscall header; the effective
config; 18 session fault controls and six service-event controls. These checks
do not establish full kernel linking or device behavior.

The matching official Manager source build is
[40109566037](https://github.com/Baka-SU/BakaSU/actions/runs/40109566037),
which succeeded at exactly the same pin. Use its
[Manager-release artifact](https://github.com/Baka-SU/BakaSU/actions/runs/40109566037/artifacts/12566655553).
APK installation, signing-certificate update compatibility and pairing on the
physical device have not been verified by this migration.

Strict Samsung stock-module CRC checks, final and embedded configuration
checks, package identity and existing attestation gates remain required.
No MODVERSIONS change, CRC rewriting or forced module loading is introduced.
