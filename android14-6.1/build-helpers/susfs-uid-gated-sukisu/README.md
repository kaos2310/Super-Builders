# Super-Builders UIDGate-v1

Local extension of the successful reference run [36463712058](https://github.com/kaos2310/Super-Builders/actions/runs/36463712058), not an upstream SUSFS release or a userspace toggle.

- SukiSU 40940 builtin: `b20dee702035af09cb2ecb5f35443bbc1747f3e6`.
- SUSFS v2.3.0: `24743360ea08d98f6ad72b856851abed8de5854f`.
- Android14 / 6.1, Samsung S928BXXU6ZZI4 / EUX; original strict KMI gates retained.

`CONFIG_KSU_SUSFS_UID_GATED_HIDING=y` adds a necessary condition to SUSFS visibility consumers: real kernel UID must be valid and `uid % 100000 >= 10000`. This covers Android app, SDK sandbox and isolated app identities across users. System app-ids (including root, system and shell) bypass those consumers in every user. It is NOT a per-package allowlist and does not grant any root permissions. Existing thread, registration, ownership and policy checks remain in force; the gate cannot enable hiding on its own. With the option disabled, the added gate returns true and preserves the previous behavior.

Coverage: suspicious path/name/inode and unicode filtering; SUS_MAP; SUS_MOUNT listing callbacks and statfs/fdinfo metadata; KSTAT consumers including redirect-registered metadata; uname; Android14 GKI bootconfig spoofing. Mount callback bypass invokes the original show function at read time; bootconfig bypass emits the original bootconfig, not an empty file. KSTAT statfs bypass returns `-EINVAL` to take the original statfs fallback.

Deliberately unchanged: raw thread flags, KernelSU authorization/session/manager ABI, administrative unmount operations, explicit OPEN_REDIRECT UID schemes 0-4, global symbol/AVC-log suppression, and ZeroMount's own routing. The legacy ZeroMount task_mmu hook remains excluded. This is not a claim that root sees a completely stock system or that all global hiding becomes UID-scoped. The pinned GKI patch changes bootconfig, not `/proc/cmdline`.

The applier rejects unknown source identities, missing/duplicate anchors and partial installations before writing. Its receipt detects later consumer changes and protects the unchanged thread/redirect functions. CI runs literal-header C tests with CONFIG on/off, multiuser boundary and credential-transition cases, and deliberate failing mutations before the expensive build. Source tests rerun after downstream patches. Package attestation checks both the final config and gzip IKCONFIG inside the packaged Image, plus the compiled enabled-features string. A sidecar config alone is not accepted. The feature is advertised through the existing SUSFS enabled-features API; no supercall or module ABI change is introduced.

Local mock tests are not device validation. A successful CI build is not proof of runtime behavior on the phone; flashing or runtime changes require a separate user request.
