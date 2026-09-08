# ReSukiSU 35119: su-session FD after successful exec

Native backport for Android 14 / Linux 6.1, retaining the existing ReSukiSU manager and ksud. This is a source-tested port; a complete kernel build and device validation are still required.

## Exact inputs

| Component | Immutable source |
| --- | --- |
| ReSukiSU 35119 | `f1dd81dc96d7f3f6691e6ac8b50fba9ae8a2f17c` |
| Existing SUSFS v2.3.0 base | `5727f79e3a7175cfb0e1a754fc2ed78eaf866237` |
| Selected upstream exec fix | `153f88df3be2501d2d33364f8fe05247aecb3cef` |
| Scoped-FD dependency used as reference | KernelSU `c72f294e09536222d450237e4c1f0271bfe145ff` |
| Port identity | `ReSukiSU-35119-SuSession-v1` |

References: [SUSFS exec fix](https://gitlab.com/simonpunk/susfs4ksu/-/commit/153f88df3be2501d2d33364f8fe05247aecb3cef), [KernelSU scoped-FD change](https://github.com/tiann/KernelSU/commit/c72f294e09536222d450237e4c1f0271bfe145ff).

The SUSFS base remains pinned to `5727f79`. Do not also apply the newer generic `10_enable_susfs_for_ksu.patch` or the newer GKI exec hunk: they expect the upstream UAPI-3 integration and would overlap this native port.

## Behavior

1. The native ReSukiSU hook explicitly reports whether an allowed `/system/bin/su` request was redirected to ksud after a successful profile change. Legacy return value `0` continues to mean several things and is not treated as proof of a su session.
2. `do_execveat_common()` installs the session FD only after `bprm_execve()` succeeds. An allocation failure is logged and does not turn a completed exec into a failed syscall return.
3. The FD has `O_CLOEXEC`: it survives the exec that created it and closes on the next exec, normally the shell started by ksud.
4. A private static cookie and the actual file-operations pointer identify the session. No user-supplied flag grants the capability, and no per-session allocation needs releasing.
5. Only `GET_WRAPPER_FD` and `DISABLE_ESCAPE_TO_ROOT` receive an additional session-based permission path. Existing root/manager/allowlist checks for every other command remain in force.
6. The wrapper creates its private inode using KSU credentials, then restores the caller credentials before publishing the FD. Error paths also restore them.
7. Failed `set_cred_ucounts()` now propagates its error from `escape_with_root_profile()`, preventing a false success signal. A pre-existing escape-disable flag also prevents granting a session capability.

The externally visible driver name remains `[ksu_driver]`, which the unchanged 35119 manager and ksud already scan. All public UAPI files remain byte-equivalent after line-ending normalization; UAPI stays at version 2. This intentionally differs from upstream's `[ksu_driver_su]` name and UAPI-3 manager requirement. Manager compatibility is supported by the source contract, not by a device test.

Normal program starts, denied su requests, disabled sucompat, no-su processes, unsupported execveat arguments, and failed profile transitions do not receive a session FD. If ksud is missing, ReSukiSU's existing shell fallback remains and does not receive the new FD. This port does not redesign the legacy profile transition that occurs before exec.

## Apply to source trees

Apply the existing pinned SUSFS GKI patch first, then run from the Super-Builders checkout:

```sh
PORT=android14-6.1/build-helpers/su-session
python3 "$PORT/apply.py" \
  --common /path/to/kernel/common \
  --ksu /path/to/kernel/KernelSU \
  --susfs-commit 5727f79e3a7175cfb0e1a754fc2ed78eaf866237

python3 "$PORT/test.py" \
  --common /path/to/kernel/common \
  --ksu /path/to/kernel/KernelSU \
  --work-dir /path/to/scratch/su-session-tests
```

The helper checks the ReSukiSU HEAD, all UAPI files, SUSFS base identity and the Linux 6.1 Makefile. Both patches must pass a dry run before either tree changes. A partially applied pair or conflicting hunk is rejected. If applying the second tree fails, touched files are restored byte-for-byte. Repeating a complete application is safe. `--verify-only` rejects an unapplied port.

The supplied `--susfs-commit` value must be the checked-out dependency identity, not a new label. The workflow obtains it from the existing SUSFS action, which verifies that checkout. The kernel helper is scoped to the existing pinned SUSFS exec integration; it does not fetch dependencies.

For Windows, `test.py --wasm --cc /path/to/clang.exe --node /path/to/node.exe --aarch64-check` compiles the same production functions as freestanding WebAssembly, executes them with Node, and also compiles an AArch64 object. Source-tree line endings follow the local Git configuration.

## Validation and CI integration

- The harness inserts the actual patched C functions and dispatch table; kernel APIs and command handlers are mocks. It exercises 267 assertions covering exec ordering, profile failures, allocation errors, dispatch permissions, wrapper credential restoration, and cleanup.
- Five mutation controls must fail: installation after failed exec, installation before exec, permissions extended to all commands, ignored ucounts errors, and omitted credential restoration.
- Application tests cover repeat application, verify-only, unknown source state, a partially applied pair, and rollback after an injected second-tree write failure.
- Source checks also exercised the existing Enhanced SUSFS KSTAT and ZeroMount dispatch transformations and the idempotent umount helper on the ported ReSukiSU tree.
- The reusable workflow has an explicit `susfs_su_session` input, default `false`; this branch's strict ZZHL workflow sets it to `true`.
- CI applies and tests the port, checks it again after later source transformations, and appends `-SuSession-v1` to artifact names. Packaging requires final `CONFIG_KSU_SUSFS=y`, the exec-site marker in the actual kernel Image, and a `RESUKISU-SU-SESSION.json` receipt containing source, patch and Image hashes.

These local checks do not validate complete kernel headers, linking, SELinux/LSM behavior, KMI/DLKM CRCs, booting, or actual manager/ksud execution. The existing strict build gates remain necessary. No new CI run, CI monitoring, flash, reboot, or device action is part of this local port preparation.

To prepare a comparison build without this port, set `susfs_su_session: false`. Keep the original ReSukiSU and SUSFS pins; the source patches are applied only when this input is enabled.
