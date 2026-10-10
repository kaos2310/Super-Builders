# BakaSU 35222 / UAPI5 / SUSFS 2.3.0 / ZeroMount integration

Base: successful [run 37831091198](https://github.com/kaos2310/Super-Builders/actions/runs/37831091198)
at Super-Builders `4619b3762a79ec464ae6bea30b4c8544293739d4` (BakaSU 35220).
Target: S928BXXU6ZZI4 / EUX, Android 14 KMI / Linux 6.1.162, full-strict KMI.

Source verified on 2026-10-10:

- BakaSU `5b76b884c75f729a220bb317aa4a4fc78f0e0e9c`: 4522 + 30700 = **35222**.
- Upstream renamed ReSukiSU to BakaSU and moved to `Baka-SU/BakaSU`.
- Internal Manager namespace is `org.bakasu.bakasu`; the default applicationId
  remains `com.resukisu.resukisu` with the same signing certificate.
- Use the matching BakaSU 35222 Manager. The upstream rename also removes
  MKSU/RKSU/SukiSU-Ultra from the built-in manager certificate list.
- SUSFS remains `24743360ea08d98f6ad72b856851abed8de5854f`, **v2.3.0**.
- Kernel and ARM64 ksud/ksuinit use the same immutable source commit.
- Upstream module scripts now receive `BAKASU=true` in place of `KSU_SUKISU=true`.

UAPI5, EVENT_SERVICES=4, the service start/skip/reset gate and scoped su-session
ABI are unchanged from 35203. The exact-pin adapter retains the explicit session
decision and successful-exec guard, while preserving upstream service handling.
OPEN_REDIRECT, Enhanced SUSFS, ZeroMount, UIDGate-v1, Gunyah reclaim, the
bootconfig static-key fix, LTO and strict Samsung DLKM CRC gates are retained.
The historical 35203 adapter and userspace verifiers remain available.

35222 retains the stale ksuinit libc lock record. `bakasu_35222_lock.py`
requires the exact commit, manifests and same-commit ksud lock, and changes only
that record to Git libc `1a661633f11a261ff9c00b40875ef72f1cbec818`, version 0.2.190.
Upstream's renamed Git dependency URLs and locked revisions remain unchanged.
Both Android dependency graphs and builds use `--locked`; CI archives the
original/effective lockfiles and build identity.

Fresh target directories and Cargo-reported OUT_DIR capture remain mandatory.
`bakasu_35222_uapi.py` checks immutable UAPI sources, generated bindings
(UAPI=5 and EVENT_SERVICES=4), and the real service-event C with six mutation
controls. The actual bindgen 0.73.2 whitespace fixture from 35203 remains valid
because the UAPI headers and bindgen source contract did not change.

Run `apply.py` after Enhanced SUSFS/ZeroMount, then `test.py` and `--verify-only`
after downstream patches. Exact-C fault tests, negative controls and packaged
Image attestations remain mandatory. CI confirms 35222 from source history and
Kbuild, verifies compiled functions, and includes test receipts in AnyKernel3.

Host tests use kernel API mocks. Concurrent requests and physical-device boot
remain unverified. Device checks need this exact Image and the matching BakaSU
Manager, including UAPI5 debug info and single service-stage execution.

From 35220 to 35222, UAPI headers and su-session consumers are unchanged.
The kernel delta is kernel/feature/selinux_hide.c (SETCURRENT permission order).
The userspace delta is userspace/ksud/Cargo.lock (rust-embed dependencies).
Kernel and userspace binaries are freshly rebuilt from the same immutable pin.
SUSFS remains 24743360 and ZeroMount remains c3cb7ff.
The existing kernel-side ZeroMount patch is retained. Its statx/readlink order,
dual SUSFS ioctl ABI, disabled legacy task_mmu hook, native UAPI5 scoped
session path and UID-gated consumers are verified against the 35222 port.

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
