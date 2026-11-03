# S928B EZIF / SukiSU 41140 / ZeroMount Guard6.13 + BRENE75

The structural baseline is successful strict run 41389393399 at
e665bad7bf1567a37d5cc8d4bfa890ad2d73694d. Firmware remains SM-S928B /
S928BXXU6EZIF / EUX, Linux 6.1.162. The official SukiSU pin is
0a4c313287b0fc0b4cf95fced30a8dccc2eb913b: 40000 + 3955 - 2815 = 41140.
Kernel, userspace and the verified official v4.3.0-r1 Manager use this exact pin.

compat.patch applies exactly to that SukiSU source. The manual built-in
lifecycle, authenticated SUSFS dispatcher, native extension ABI 2, session
decision and forced-state replay remain integrated. The port preserves the
new native SELinux inode/symbol-resolver initialization and AVC policy sequence
handling. Native selinux_hide.c is byte-identical to official SukiSU 41140;
parallel common-tree manual SELinux hooks are reversed. Native preinit remains
disabled for this manual-hook profile. No UAPI6 or manager-authentication
substitute is used.

The established SUSFS v2.3.0 base 5369359d remains pinned. The official
Android14/6.1 branch was freshly fetched on 2026-11-03 and still reports
v2.3.0 at a0ac9069, unchanged since the successful 41131 build. Its latest priority
filter, packages.list parser, Kconfig and feature advertisement are imported
from a0ac906915c8a8d50d474dfb3cae478ef32edc1a as a separate hash-bound overlay.
The native SukiSU SELinux implementation is retained instead of mixing it with
upstream's parallel manual SELinux refactor. This is a downstream adaptation,
not a claim of a byte-identical complete upstream kernel patch stack.
See ../susfs-priority-uid-41140/SOURCE.json and README.md for the exact scope.

ZeroMount kernel hooks, OPEN_REDIRECT, UIDGate, Gunyah and DroidSpaces are
retained. CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER=y is explicitly required in the
generated 41140 config and embedded Image audit. The companion user-provided
Guard6.13 module gains the two BRENE75 functions through
../zeromount-brene75-41140/, with exact 41140 CLI tests, non-destructive directory
views and preservation of existing settings. The native ARM64 module binaries
are unchanged. The complete module ZIP is produced locally from the two
hash-pinned user inputs; CI also builds the separate upstream base-detector
compatibility artifact.

Fresh local evidence covers 57 ARM64 objects, 197 replayed kernel/UAPI sources,
55 effective config settings and both real Android Cargo graphs (232 nodes
each) with the unchanged official workspace Cargo.lock. Native extension,
session, service, mount, priority-parser, UIDGate, Gunyah, KPM bridge/event,
Image-recovery and package controls pass. KPM remains paired with KernelPatch
1c5b6089, bridge ABI 2. Original.Image retention and post-ABI transformation
checks remain mandatory.

Full kernel link, final Samsung stock-module CRC/KMI, full Android userspace
binaries and final flash-package attestations remain CI gates. No phone was
flashed, rebooted, installed or tested. Host boundary mocks and local object
compilation do not establish physical boot, runtime behavior or concurrency.

The nine official commits from 41131 to 41140 change Manager features only.
Kernel, UAPI, userspace and both workspace manifests/lock are byte-identical
between the two pins before the deterministic version configuration.
KPM and BRENE75 helpers are isolated in version-specific folders for 41140.

41140 retains native SELinux inode/symbol-resolver initialization and policy sequence handling.
Latest SUSFS priority parsing/config changes are recorded in ../susfs-priority-uid-41140/SOURCE.json.
The complete user-provided Guard6.13 module is extended by ../zeromount-brene75-41140/.
