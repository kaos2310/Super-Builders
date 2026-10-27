# BakaSU 35252 / UAPI6 scoped-session adapter

The successful baseline is [39047475246](https://github.com/kaos2310/Super-Builders/actions/runs/39047475246)
(BakaSU 35231 / S928B EZIF). Kernel, ksud and ksuinit now share immutable pin
`d5e9e025b8b49155f8014684d64c91742b465f65`, version 35252, UAPI6.

Upstream changed its exec interface to carry a filename pointer so preinit can
select the new filename. The adapter retains that pointer flow and all new
upstream init/preinit handling. It adds a local scoped implementation behind
the original public `ksu_handle_execve_common` signature. The new post-exec
common interface is retained.

Only a recognized ksud session with successful exec may receive the scoped
su-session FD. Credential failures, missing ksud and escape-disabled tasks
cannot select a session. The legacy flag is consumed after an exec attempt,
and the existing WebView UID 1053 profile/credential boundaries are retained.
Production C is extracted for the fault harness, which rejects 18 mutations.

`bakasu_35252_uapi.py` requires exact upstream UAPI6 headers and native
userspace consumers, checks fresh Cargo-reported bindings for UAPI6 and
EVENT_SERVICES=4, and exercises the real service start/skip/reset function
with six mutation controls. Old UAPI5 bindings must be rejected. The known
bindgen whitespace fixture is used only as a formatting regression with its
version token explicitly changed; it is not evidence of a new generated build.

Both original upstream lockfiles resolve without repair. The earlier 35231
libc correction is not applied to 35252. Both Android graphs passed
`cargo metadata --locked --filter-platform aarch64-linux-android`, with
18 resolved nodes for ksuinit and 207 for ksud. Both files stayed byte-identical
to the immutable source pin. Full ARM64 Rust builds remain CI work.

Run `apply.py` after the preserved Enhanced SUSFS/ZeroMount transforms, then
the exact-C tests and source verification. The existing final Image, compiled
function, KMI/stock-CRC and package-attestation checks remain mandatory.
CPU/PID limits stay disabled. The full new kernel link, stock-module ABI,
Manager installation and physical-device runtime remain unverified locally.
