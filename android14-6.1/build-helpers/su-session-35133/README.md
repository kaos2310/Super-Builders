# ReSukiSU 35133 with SUSFS 2.3.0

This adapter targets ReSukiSU `6930e97b59f8f5a7a2e75583f7be1cf982856157`
and SUSFS `153f88df3be2501d2d33364f8fe05247aecb3cef`, the
`gki-android14-6.1` head checked on 2026-09-11. The version is
`30700 + 4433 = 35133`; the native UAPI version remains 4.

Build base: [34501538739](https://github.com/kaos2310/Super-Builders/actions/runs/34501538739).
Behavior reference: [34262304602](https://github.com/kaos2310/Super-Builders/actions/runs/34262304602).

The latest SUSFS patch introduces a local session boolean and post-success FD
installation in `fs/exec.c`. ReSukiSU also returns zero when falling back to
`/system/bin/sh` because `ksud` is missing. That return code alone cannot identify
a real su session. The adapter retains the upstream success guard, supplies an
explicit boolean only after selecting `KSUD_PATH`, and carries the reference
root-profile error propagation and WebView UID 1053 profile handling forward.
The native UAPI4 definitions, scoped driver implementation and ksud interface
are checked against the immutable upstream source.

Run `apply.py` after the pinned SUSFS patch, then `test.py` after all downstream
patches. `apply.py --verify-only` never applies the adapter again. Writes are
restored if transformation or verification fails. Unexpected pins, ambiguous
source state and repeated application fail closed.

The C tests extract actual production functions rather than reimplementing
their behavior. They cover exec ordering, missing ksud, credential and allocation
failures, driver descriptor permissions, wrapper cleanup and WebView profiles.
Nine deliberately broken variants must fail. Local testing supports WebAssembly
and AArch64 object compilation; CI executes the tests as native Linux binaries.

The final gate checks generated config, Image identity and unique executable
symbols in unstripped vmlinux. The flash ZIP contains the final config,
`RESUKISU-SUSFS-INTEGRATION.json` and `RESUKISU-SUSFS-TESTS.json`.
These are build and mocked control-flow checks. Boot, SELinux behavior and live
SUSFS/ZeroMount module operation require testing this exact Image on the device.
