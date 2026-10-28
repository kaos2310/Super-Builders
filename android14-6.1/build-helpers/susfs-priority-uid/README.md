# Priority UID filter for S928B EZIF / SukiSU 41098

The successful 41096 build (40577344297) used SUSFS 5369359d and did not
contain the priority UID filter. This bounded backport retains that baseline
and imports the official filter from simonpunk/susfs4ksu, gki-android14-6.1,
commit 8b25990241174fe88d2131a9929e36b5e5ffb1d0. This includes the initial
08066fae feature and the subsequent RCU and package-worker corrections.

The four hooks cover getpriority, setpriority, ioprio_get and ioprio_set.
Command 0x60030 replaces the selected package list, resolves UIDs in
10000-19999 and uses modulo 100000 for Android secondary users. Failed
requests retain the previous bitmap. Package changes refresh the list after
track_throne(false), outside the fsnotify callback locks. CONFIG_KSU_SUSFS=y
is the upstream configuration dependency; no invented Kconfig symbol is used.

common.patch adapts only insertion context to the existing logging/Enhanced
SUSFS tree. The official filter functions and credential helpers are retained.
The SukiSU compatibility patch adds the command and package-observer calls.
CI applies the common patch after Enhanced SUSFS/ZeroMount and before UIDGate,
so the existing UIDGate integrity receipt covers the resulting header.

Independent local checks compile fs/susfs.o, kernel/sys.o, block/ioprio.o and
the full SukiSU subtree for ARM64. The host harness compiles the actual parser,
filter, replacement operation and worker with kernel API mocks. It checks
package validation, UID bounds, secondary users, failed request preservation,
reinstall/uninstall refresh, allocation/copy/domain errors, worker exclusion
and clearing with the manager's comma sentinel. Four mutations must fail.
These are sequential host checks, not a device or concurrency proof.

The final CI gate checks the linked filter symbols, packaged Image marker,
embedded CONFIG_KSU_SUSFS=y and source receipt, and includes its attestation
and semantic-test receipt in the flash ZIP. Failure prevents packaging.
The official Manager 41098 includes the matching native ksud filter command.
No device was flashed, rebooted or configured during this preparation.
