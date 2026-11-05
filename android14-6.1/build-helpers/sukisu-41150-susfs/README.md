# SM-S928B EZIF with SukiSU 41150

This profile extends the existing 41141 EZIF build on Linux 6.1.162.
The official SukiSU v4.3.0-r2 tag resolves to
645ef9860b9b7f900bb5d1b27e224f2c311d39c0.
The version calculation is 40000 + 3965 - 2815 = 41150.
Kernel, UAPI, userspace and workspace lock are byte-identical to official
41141 before the deterministic version configuration.
The official 41150 Manager APK signature and ARM64 support were verified.
See ../sukisu-kpm-41150/MANAGER-COMPATIBILITY.json.

The official SuSFS gki-android14-6.1 head was fetched on 2026-11-06.
It remains a0ac906915c8a8d50d474dfb3cae478ef32edc1a and reports v2.3.0.
Integration uses the audited 5369359d base plus the current a0ac9069
priority filter, packages.list parser, Kconfig and feature advertisement.
Native SukiSU SELinux handling is retained. The complete upstream manual
SELinux refactor is outside this adapted patch stack.
See UPSTREAM-VERIFICATION.json and ../susfs-priority-uid-41150/SOURCE.json.

Fresh verification covers 57 ARM64 objects, replay of 197 kernel/UAPI sources,
both locked Android Cargo graphs, 55 effective configuration settings,
session faults, UAPI services, extension ABI 2, priority filter, UIDGate,
Gunyah, KPM bridge ABI 2, bounded Image transformations and package rejection
controls. The production entry point requires matching hash-bound proof.
The KPM Image transformation test uses a historical Linux 6.1.162 fixture.
The final 41150 Image requires the strict CI kernel link and Samsung CRC/KMI gates.

ZeroMount Guard6.13 with BRENE75 is rebuilt with the exact 41150 CLI contract.
Its delivered archive passed 35 adapter tests, nine CLI cases, checksum
validation and the WebUI allowlist tests.
KPM, DroidSpaces, OPEN_REDIRECT and the existing CPU/PID configuration
remain part of the inherited build profile.

Full kernel link, full Android userspace compilation, Samsung stock-module
CRC/KMI, physical boot and device concurrency are pending.
See ../sukisu-41150-migration-verification.json for the measured scope.
