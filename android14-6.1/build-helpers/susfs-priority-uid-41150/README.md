# Latest SUSFS priority filter for S928B EZIF / SukiSU 41150

Verified 2026-11-06: the official gki-android14-6.1 branch still reports
SUSFS v2.3.0. Its current pin is a0ac906915c8a8d50d474dfb3cae478ef32edc1a.
This strict Samsung port retains the successful 5369359d base and native
SukiSU SELinux implementation, then imports the latest official priority
filter, parser, Kconfig, feature advertisement and syscall hooks as a
hash-bound overlay. Parallel manual upstream SELinux hooks are not mixed
with native SukiSU SELinux; this is an explicit downstream adaptation.

CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER=y is now required in addition to
CONFIG_KSU_SUSFS=y. The feature appears in the enabled-features response.
UID resolution reads /data/system/packages.list with O_NOATIME and a
4 MiB limit. It handles secondary Android users and retains the RCU and
package-worker corrections. Current upstream skips unresolved packages;
syntactically invalid names still fail. This differs from the earlier
8b259902 parser. Command 0x60030 replaces the entire selected list.

The exact parser/filter/worker functions are compiled and host-tested with
kernel API boundary mocks. Tests cover noatime, bounds, short reads, failed
opens, invalid input, replacements, missing packages, reinstall/uninstall,
allocation/copy/domain faults and worker exclusion. Four deliberately broken
variants must fail. Actual kernel/sys.c and block/ioprio.c compile for ARM64.
The packaging gate requires the new config flag in the embedded Image and
compiled filter functions in vmlinux. Concurrency and phone runtime are not
proven by these sequential host checks.

ZeroMount Guard6.13 + BRENE75 uses the actual SukiSU 41150 CLI and queries
this exact feature before applying optional third-party UID filtering.
See ../zeromount-brene75-41150/README.md for module scope, retained configuration,
non-destructive directory views and device-verification limits.
