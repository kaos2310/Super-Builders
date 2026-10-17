# BakaSU 35231 / UAPI5 / SUSFS 2.3.0 / ZeroMount integration

Base: successful [run 38824525197](https://github.com/kaos2310/Super-Builders/actions/runs/38824525197)
at Super-Builders `7d0eeffaf94e64a54eef4249fc25fdc212052ba3` (BakaSU 35229).
Target: S928BXXU6EZIF / EUX, Android 14 KMI / Linux 6.1.162, full-strict KMI.

Source verified on 2026-10-17:

- BakaSU `2489b38582a08fee7b586d05185da5e5d12c6a5c`: 4531 + 30700 = **35231**.
- Upstream renamed ReSukiSU to BakaSU and moved to `Baka-SU/BakaSU`.
- Internal Manager namespace is `org.bakasu.bakasu`; the default applicationId
  remains `com.resukisu.resukisu` with the same signing certificate.
- Use the matching BakaSU 35231 Manager. The upstream rename also removes
  MKSU/RKSU/SukiSU-Ultra from the built-in manager certificate list.
- SUSFS advances to `5369359dbd10f6dd8cbdd59d1df7b788b29b168c`, **v2.3.0**.
- Kernel and ARM64 ksud/ksuinit use the same immutable source commit.
- Upstream module scripts now receive `BAKASU=true` in place of `KSU_SUKISU=true`.

UAPI5, EVENT_SERVICES=4, the service start/skip/reset gate and scoped su-session
ABI are unchanged from 35203. The exact-pin adapter retains the explicit session
decision and successful-exec guard, while preserving upstream service handling.
It also preserves 35231's ksud existence check before committing root credentials.
The obsolete manual SELinux hooks are replaced by the independently compiled
native port documented in `../bakasu-35231-susfs/README.md`.
OPEN_REDIRECT, Enhanced SUSFS, ZeroMount, UIDGate-v1, Gunyah reclaim, the
bootconfig static-key fix, LTO and strict Samsung DLKM CRC gates are retained.
The historical 35203 adapter and userspace verifiers remain available.

35231 retains the stale ksuinit libc lock record. `bakasu_35231_lock.py`
requires the exact commit, manifests and same-commit ksud lock, and changes only
that record to Git libc `1a661633f11a261ff9c00b40875ef72f1cbec818`, version 0.2.191.
Upstream's renamed Git dependency URLs and locked revisions remain unchanged.
Upstream now records the prettyplease dependency itself; ksud Cargo.lock remains byte-identical to the 35231 source pin.
Both Android dependency graphs and builds use `--locked`; CI archives the
original/effective lockfiles and build identity.

Fresh target directories and Cargo-reported OUT_DIR capture remain mandatory.
`bakasu_35231_uapi.py` checks immutable UAPI sources, generated bindings
(UAPI=5 and EVENT_SERVICES=4), and the real service-event C with six mutation
controls. The actual bindgen 0.73.2 whitespace fixture from 35203 remains valid
because the UAPI headers and bindgen source contract did not change.

Run `apply.py` after Enhanced SUSFS/ZeroMount, then `test.py` and `--verify-only`
after downstream patches. Exact-C fault tests, negative controls and packaged
Image attestations remain mandatory. CI confirms 35231 from source history and
Kbuild, verifies compiled functions, and includes test receipts in AnyKernel3.

Host tests use kernel API mocks. Concurrent requests and physical-device boot
remain unverified. Device checks need this exact Image and the matching BakaSU
Manager, including UAPI5 debug info and single service-stage execution.

From the successful 35229 baseline to 35231, kernel, UAPI headers, userspace
sources and su-session consumers are unchanged. Only upstream Renovate and
ksud Cargo.lock changed. Upstream now includes the direct prettyplease edge
and selects Git libc 0.2.191; the audited ksuinit repair copies that same record.
Kernel and userspace binaries are freshly rebuilt from the same immutable pin.
SUSFS advances four commits to 5369359d and ZeroMount remains c3cb7ff.
The updated SUSFS patch removes one unused exec declaration; the exact-pin
session adapter accepts the new declaration block. Its functional C is retained.
The existing kernel-side ZeroMount patch is retained. Its statx/readlink order,
dual SUSFS ioctl ABI, disabled legacy task_mmu hook, native UAPI5 scoped
session path and UID-gated consumers are verified against the 35231 port.

The separate ZeroMount module job applies the exact two-site BakaSU flag patch
at c3cb7ff: installer and Rust detection accept `BAKASU=true` or
`KSU_SUKISU=true`. The kernel remains the authoritative SUSFS probe. Without
an external SUSFS module, Enhanced mode still requires the SUSFS userspace
binary; otherwise Embedded/Absent classification is preserved. The job tests
16 shell flag cases and 128 Rust classification cases, rejects a legacy-only
detector mutation, builds Android ARM64 with the pinned Cargo.lock, then packages
the binary and patched installer with the checksum-pinned official WebUI and
auxiliary files. The compatibility ZIP and build identity are separate artifacts.
This addresses the BakaSU classification conflict; no device installation log
was supplied to diagnose an additional installer abort.
