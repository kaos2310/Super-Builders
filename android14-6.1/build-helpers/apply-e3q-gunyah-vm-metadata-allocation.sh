#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-vm-metadata-allocation.sh <kernel-tree>}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_COMMIT="9bf8da21bb7e5891bb9b4ef917893a5792874608"
TMP_DIR="$(mktemp -d -t e3q-gunyah-35089.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

# Replay the runtime-proven IRQFD/RM diagnostic baseline while consuming the
# current bounded-backing generator. The e3q runtime now proves that removing
# the 8192 total-entry guard lets a heavily fragmented normal-GuestMemory
# fallback enter a host-stalling RM path. Keep the guard as a safety circuit
# breaker, while preserving RM MEM_APPEND for valid parcels <= 8192 entries.
BASE_HELPER="$TMP_DIR/apply-e3q-gunyah-vm-metadata-allocation.sh"
cp "$SCRIPT_DIR/apply-e3q-gunyah-cma-compat.sh" "$TMP_DIR/apply-e3q-gunyah-cma-compat.sh"
curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
  "https://raw.githubusercontent.com/kaos2310/Super-Builders/${BASE_COMMIT}/android14-6.1/build-helpers/apply-e3q-gunyah-vm-metadata-allocation.sh" \
  -o "$BASE_HELPER"
grep -qF 'GH_DIAG mem_share refused' "$BASE_HELPER"
grep -qF 'mapping->parcel.n_mem_entries > 8192' "$BASE_HELPER"
grep -qF 'ret = -E2BIG;' "$BASE_HELPER"
grep -qF 'GH_DIAG rm_mem_share call begin' "$BASE_HELPER"
grep -qF 'GH_DIAG rm_append sequence begin' "$BASE_HELPER"
grep -qF 'GH_RM_RPC_MEM_APPEND' "$BASE_HELPER"
grep -qF 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$BASE_HELPER"
bash "$BASE_HELPER" "$KERNEL_TREE"

GUNYAH_DIR="$KERNEL_TREE/drivers/virt/gunyah"
VM_TARGET="$GUNYAH_DIR/vm_mgr.c"
RM_RPC="$GUNYAH_DIR/rsc_mgr_rpc.c"

# The existing QCOM follow-up helper was written during the guard-removal
# experiment and validates that temporary source shape. Remove the exact guard
# only while that source transform runs, then restore it before any kernel build.
# No compiled artifact is ever allowed to leave this helper without the guard.
python3 - "$VM_TARGET" "$RM_RPC" <<'PY'
from pathlib import Path
import sys

vm = Path(sys.argv[1])
rpc = Path(sys.argv[2])
source = vm.read_text()
rpc_source = rpc.read_text()
marker = "if (mapping->parcel.n_mem_entries > 8192) {"

if source.count(marker) != 1:
    raise SystemExit(
        f"FATAL: expected exactly one diagnosed 8192 mem-share guard, found {source.count(marker)}"
    )
if source.count("GH_DIAG mem_share refused") != 1:
    raise SystemExit("FATAL: diagnosed GH_DIAG mem_share refusal marker is not unique")

start = source.index(marker)
brace = source.index("{", start)
depth = 0
end = None
for pos in range(brace, len(source)):
    ch = source[pos]
    if ch == "{":
        depth += 1
    elif ch == "}":
        depth -= 1
        if depth == 0:
            end = pos + 1
            break
if end is None:
    raise SystemExit("FATAL: unterminated 8192 mem-share guard")

block = source[start:end]
for required in (
    "GH_DIAG mem_share refused",
    "mapping->parcel.n_mem_entries > 8192",
    "ret = -E2BIG;",
    "goto err;",
):
    if required not in block:
        raise SystemExit(f"FATAL: diagnosed guard shape changed; missing {required!r}")

# Persist the exact baseline block so the same text is restored after the QCOM
# transform. This avoids reconstructing indentation or error flow by hand.
Path(str(vm) + ".e3q_guard").write_text(block)
remove_end = end
if source[remove_end:remove_end + 2] == "\n\n":
    remove_end += 2
elif source[remove_end:remove_end + 1] == "\n":
    remove_end += 1
source = source[:start] + source[remove_end:]

checks = {
    "temporary guard removal": marker not in source,
    "temporary refusal removal": "GH_DIAG mem_share refused" not in source,
    "mem-share begin retained": "GH_DIAG mem_share begin" in source,
    "mem-share end retained": "GH_DIAG mem_share end" in source,
    "RM MEM_APPEND opcode present": "GH_RM_RPC_MEM_APPEND" in rpc_source,
    "RM append helper present": "static int gh_rm_mem_append(" in rpc_source,
    "RM append RPC helper present": "static int _gh_rm_mem_append(" in rpc_source,
    "RM initial share diagnostics retained": "GH_DIAG rm_mem_share call begin" in rpc_source,
    "RM append sequence diagnostics retained": "GH_DIAG rm_append sequence begin" in rpc_source,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("FATAL: temporary Gunyah source preparation failed: " + ", ".join(failed))

vm.write_text(source)
print("Temporarily removed e3q 8192 guard for legacy QCOM source transform; guard will be restored before build")
PY

FOLLOWUP="$SCRIPT_DIR/apply-e3q-gunyah-qcom-vmid-compat.sh"
KMI_HELPER="$SCRIPT_DIR/allow-e3q-gunyah-rm-vmid-kmi.sh"
for helper in "$FOLLOWUP" "$KMI_HELPER"; do
  test -s "$helper" || { echo "FATAL: missing e3q Gunyah helper: $helper" >&2; exit 1; }
  bash -n "$helper"
done
bash "$FOLLOWUP" "$KERNEL_TREE"
bash "$KMI_HELPER" "$KERNEL_TREE"

# Restore the exact proven 8192 safety guard before compilation. Insert it
# immediately before GH_DIAG mem_share begin, which is the same location used
# by the diagnosed baseline helper.
python3 - "$VM_TARGET" <<'PY'
from pathlib import Path
import re
import sys

vm = Path(sys.argv[1])
guard_file = Path(str(vm) + ".e3q_guard")
if not guard_file.is_file():
    raise SystemExit("FATAL: saved e3q 8192 guard block is missing")
source = vm.read_text()
guard = guard_file.read_text()
marker = "if (mapping->parcel.n_mem_entries > 8192) {"

if marker in source or "GH_DIAG mem_share refused" in source:
    raise SystemExit("FATAL: guard unexpectedly present before controlled restoration")

pattern = re.compile(
    r'(?P<i>^[ \t]*)pr_info\("GH_DIAG mem_share begin vmid=%u label=%u type=%u entries=%zu\\n",',
    re.MULTILINE,
)
matches = list(pattern.finditer(source))
if len(matches) != 1:
    raise SystemExit(
        f"FATAL: expected one GH_DIAG mem_share begin insertion point, found {len(matches)}"
    )
insert = matches[0].start()
source = source[:insert] + guard + "\n\n" + source[insert:]
vm.write_text(source)
guard_file.unlink()

checks = {
    "8192 guard restored once": source.count(marker) == 1,
    "refusal marker restored once": source.count("GH_DIAG mem_share refused") == 1,
    "E2BIG retained": "ret = -E2BIG;" in source,
    "mem-share begin retained": "GH_DIAG mem_share begin" in source,
    "guard precedes share": source.index(marker) < source.index("GH_DIAG mem_share begin"),
    "obsolete 512 total guard absent": "mapping->parcel.n_mem_entries > 512" not in source,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("FATAL: e3q 8192 guard restoration failed: " + ", ".join(failed))

print("Restored e3q 8192-total-entry Gunyah safety guard before kernel compilation")
PY

QCOM_SRC="$GUNYAH_DIR/gunyah_qcom.c"
BACKING_SRC="$GUNYAH_DIR/cma_compat.c"
GUNYAH_MAKEFILE="$GUNYAH_DIR/Makefile"
FIRMWARE_MAKEFILE="$KERNEL_TREE/drivers/firmware/Makefile"
MODULES_BZL="$KERNEL_TREE/modules.bzl"
QCOM_SCM_HEADER="$KERNEL_TREE/include/linux/qcom_scm.h"
ABI_LIST="$KERNEL_TREE/android/abi_gki_aarch64"

# Final fail-closed assertions. The compiled kernel must contain the 8192 total
# parcel guard AND the 512-entry RM MEM_APPEND implementation/diagnostics.
grep -qF 'mapping->parcel.n_mem_entries > 8192' "$VM_TARGET"
grep -qF 'GH_DIAG mem_share refused' "$VM_TARGET"
grep -qF 'ret = -E2BIG;' "$VM_TARGET"
grep -qF 'GH_DIAG mem_share begin' "$VM_TARGET"
grep -qF 'GH_DIAG mem_share end' "$VM_TARGET"
! grep -qF 'mapping->parcel.n_mem_entries > 512' "$VM_TARGET"

grep -qF 'GH_RM_RPC_MEM_APPEND' "$RM_RPC"
grep -qF 'static int gh_rm_mem_append(' "$RM_RPC"
grep -qF 'static int _gh_rm_mem_append(' "$RM_RPC"
grep -qF 'GH_DIAG rm_mem_share call begin' "$RM_RPC"
grep -qF 'GH_DIAG rm_append sequence begin' "$RM_RPC"
grep -qF 'GH_DIAG rm_append batch begin' "$RM_RPC"
grep -qF 'GH_DIAG rm_append call begin' "$RM_RPC"

grep -qF '#define GH_EXTENT_MIN_ORDER 3U' "$BACKING_SRC"
grep -qF '#define GH_EXTENT_LIMIT 8192UL' "$BACKING_SRC"
grep -qF 'alloc_contig_pages(1UL << try_order, gfp, NUMA_NO_NODE, NULL)' "$BACKING_SRC"
grep -qF '__free_page(nth_page(chunk->base, i));' "$BACKING_SRC"
! grep -qF 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$BACKING_SRC"

grep -qF 'static u16 qcom_scm_map_vmid(u16 vmid)' "$QCOM_SRC"
grep -qF 'gh_rm_get_vmid(rm, &self_vmid)' "$QCOM_SRC"
grep -qF 'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' "$QCOM_SRC"
grep -qF 'new_perms[n].vmid = qcom_scm_map_vmid(vmid);' "$QCOM_SRC"
grep -qF 'src |= BIT_ULL(qcom_scm_map_vmid(vmid));' "$QCOM_SRC"
! grep -qF 'GH_QCOM_SCM' "$QCOM_SRC"

grep -qF 'EXPORT_SYMBOL_GPL(gh_rm_get_vmid);' "$RM_RPC"
grep -Eq '^[[:space:]]*gh_rm_get_vmid[[:space:]]*$' "$ABI_LIST"
grep -qF 'extern int qcom_scm_assign_mem(' "$QCOM_SCM_HEADER"

grep -qF 'obj-m += gunyah_qcom.o # e3q vendor_boot live-test module; not packaged by AnyKernel' "$GUNYAH_MAKEFILE"
grep -qF 'obj-m += qcom-scm.o # e3q vendor_boot build-only provider; not packaged by AnyKernel' "$FIRMWARE_MAKEFILE"
grep -Eq '^qcom-scm-objs[[:space:]]*\+=[[:space:]]*qcom_scm\.o[[:space:]]+qcom_scm-smc\.o[[:space:]]+qcom_scm-legacy\.o' "$FIRMWARE_MAKEFILE"
grep -qF '"drivers/firmware/qcom-scm.ko",' "$MODULES_BZL"
grep -qF '"drivers/virt/gunyah/gunyah_qcom.ko",' "$MODULES_BZL"

! grep -qF 'E3Q_GUNYAH_VENDOR_SCM_API' "$GUNYAH_MAKEFILE"
! grep -qF 'E3Q_GUNYAH_VENDOR_SCM_API' "$QCOM_SCM_HEADER"

echo 'e3q Gunyah 35089 preflight complete: 8192 safety guard restored + 512-entry RM MEM_APPEND + bounded RAM + SCM VMID mapping + qcom-scm CI provider + additive KMI allowance + safe teardown'
