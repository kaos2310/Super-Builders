# ReSuSFS for SukiSU 41165 / SUSFS 2.4.0

Based on the official ReSuSFS v26.10.23 release by Ahmed Al-Nassif. Its existing
WebUI, rule editors, user scripts, cron settings, early/late phases, profiles and
translations are retained. A native-looking card in the SUSFS tab adds:

- UID-Gated Hiding, Hidden Name, Unicode and symbol-hiding Runtime-v1 controls.
- A Priority-UID package list, with explicit apply/save and clear operations.
- Read-only kernel, owner, capability and generation status.

New selections are optional. Opening the card reads status without creating
settings or changing the kernel. Runtime writes require the exact ABI, supported
feature bit, matching generation and readback. Selections are saved only after a
confirmed write and restored only while ReSuSFS remains the active owner.
Priority UID has no independent kernel getter; its UI explicitly displays the
saved list and distinguishes the syscall acknowledgement from kernel readback.

The private `bin/ksu_susfs` is compiled from vendored official C source pinned to
`a2165b6f875b73e2f87d3c6f12814efac8de061d`, not binary-patched. It preserves the
LP64 SUSFS command ABI. Kernels reporting exactly v2.3.0 or v2.4.0 are supported;
unknown releases keep queries available but block writes. Runtime-v1 requires
the corresponding KAOSLAB kernel extension; unavailable controls stay disabled.

ReSuSFS must be active and selected as SUSFS owner, with no other active SUSFS
module and ZeroMount's SUSFS master/config disabled. No action here transfers
ownership, enables ZeroMount/BRENE, or edits their configuration. The global
SUSFS CLI and existing boot-value/writer adapters are retained untouched.

The flash installer preserves an existing `/data/adb/ReSuSFS` directory exactly.
Only a fresh installation receives upstream default files. New Runtime and
Priority preferences are created only by explicit user action. The module's
module-manager action button reads status. The WebUI's existing apply-profile
button remains available; its obsolete force-update control is hidden only in
the SUSFS tab (the UserHub import button is retained). CLI updates use this package instead
of replacing a global binary from an unpinned download.

Build and package:

```sh
python build_tool.py --ndk "$ANDROID_NDK_ROOT" --output module-output/ksu_susfs
python package.py --runtime-helper module-output/susfs-runtime --susfs-tool module-output/ksu_susfs --output module-output
python test.py
node test.mjs
```

Flash the resulting ZIP through SukiSU's module installer. No device installation
or reboot is performed by these build tools. Runtime state changes are global;
the UI asks for confirmation and uses the kernel's generation check to reject
stale requests. A new kernel boot and full module lifecycle remain separate
device validation steps.
