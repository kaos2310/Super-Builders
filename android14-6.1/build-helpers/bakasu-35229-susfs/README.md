# BakaSU 35229 / SUSFS 2.3.0 compatibility port

Target: SM-S928B / S928BXXU6EZIF / EUX, Android 14 KMI, Linux 6.1.162.

BakaSU is pinned to `d7260ca1e5c128061122924d0d48754e361e135c`:
30700 + 4529 commits = version 35229. SUSFS remains pinned to
`24743360ea08d98f6ad72b856851abed8de5854f`.

Upstream deliberately rejects SUSFS builds after changing SELinux hiding.
This bounded downstream port reverses only the obsolete SUSFS manual hooks
in `security/selinux/hooks.c` and `security/selinux/selinuxfs.c`. BakaSU's new
native SELinux implementation remains byte-identical to the pinned upstream.
SUSFS AVC logging, filesystem features, UIDGate and ZeroMount remain present.
Native symbol resolution requires `CONFIG_KALLSYMS_ALL=y`.

`apply.py` rejects missing or mismatched independent evidence before writes.
The evidence binds the exact patch, port source, effective configuration and
ARM64 object hashes. `--preflight` retains the original block unless the
explicit isolated test-build variable is supplied. Release application
requires the matched `PREFLIGHT.json`; `check.py` verifies the resulting
sources again after downstream transforms and before packaging.

The UAPI5 scoped-session adapter preserves the newer upstream check that ksud
exists before committing root credentials. Missing ksud does not select a
scoped session. Eighteen negative controls exercise exec failure, ordinary
exec, credential failure, missing ksud, ioctl scope, stale flags and WebView
policy boundaries.

Independent local evidence includes ARM64 compilation of SELinux avc, hooks,
selinuxfs and services; BakaSU selinux_hide, sepolicy and sucompat; and fs/exec.
These are compile and mocked-C checks. Full kernel linking, strict Samsung
module CRC checks, the final embedded configuration and package attestation
remain mandatory CI gates. Device installation and runtime behavior have not
been tested.

The user's final configuration omits CPU and PID limits:
`CONFIG_CGROUP_PIDS=n`, `CONFIG_CFS_BANDWIDTH=n`. All other requested IPC,
namespace, devtmpfs, NAT66, firewall, ipset and tmpfs ACL/xattr features are
verified in both final and extracted embedded configurations. Linux 6.1 uses
`CONFIG_IP_NF_TARGET_REJECT` and `CONFIG_IP6_NF_TARGET_REJECT` for REJECT.
