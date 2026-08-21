#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-vm-metadata-allocation.sh <kernel-tree>}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_COMMIT="9bf8da21bb7e5891bb9b4ef917893a5792874608"
TMP_DIR="$(mktemp -d -t e3q-gunyah-35088.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

# Replay the last runtime-proven 8192/memshare baseline, but let it consume the
# current bounded-backing generator. The follow-up below changes only the newly
# diagnosed SCM-VMID and contig teardown paths plus CI-only module outputs.
BASE_HELPER="$TMP_DIR/apply-e3q-gunyah-vm-metadata-allocation.sh"
cp "$SCRIPT_DIR/apply-e3q-gunyah-cma-compat.sh" "$TMP_DIR/apply-e3q-gunyah-cma-compat.sh"
curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
  "https://raw.githubusercontent.com/kaos2310/Super-Builders/${BASE_COMMIT}/android14-6.1/build-helpers/apply-e3q-gunyah-vm-metadata-allocation.sh" \
  -o "$BASE_HELPER"
grep -qF 'GH_DIAG mem_share refused' "$BASE_HELPER"
grep -qF 'mapping->parcel.n_mem_entries > 8192' "$BASE_HELPER"
grep -qF 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$BASE_HELPER"
bash "$BASE_HELPER" "$KERNEL_TREE"

FOLLOWUP="$SCRIPT_DIR/apply-e3q-gunyah-qcom-vmid-compat.sh"
KMI_HELPER="$SCRIPT_DIR/allow-e3q-gunyah-rm-vmid-kmi.sh"
for helper in "$FOLLOWUP" "$KMI_HELPER"; do
  test -s "$helper" || { echo "FATAL: missing e3q Gunyah helper: $helper" >&2; exit 1; }
  bash -n "$helper"
done
bash "$FOLLOWUP" "$KERNEL_TREE"
bash "$KMI_HELPER" "$KERNEL_TREE"

GUNYAH_DIR="$KERNEL_TREE/drivers/virt/gunyah"
QCOM_SRC="$GUNYAH_DIR/gunyah_qcom.c"
BACKING_SRC="$GUNYAH_DIR/cma_compat.c"
GUNYAH_MAKEFILE="$GUNYAH_DIR/Makefile"
FIRMWARE_MAKEFILE="$KERNEL_TREE/drivers/firmware/Makefile"
MODULES_BZL="$KERNEL_TREE/modules.bzl"
VM_TARGET="$GUNYAH_DIR/vm_mgr.c"
RM_RPC="$GUNYAH_DIR/rsc_mgr_rpc.c"
QCOM_SCM_HEADER="$KERNEL_TREE/include/linux/qcom_scm.h"
ABI_LIST="$KERNEL_TREE/android/abi_gki_aarch64"

# Final pre-build assertions: runtime fix, exportability, KMI allowance, Kleaf
# declaration and the original safety guard must coexist before the expensive build.
grep -qF 'mapping->parcel.n_mem_entries > 8192' "$VM_TARGET"
grep -qF 'ret = -E2BIG;' "$VM_TARGET"
grep -qF 'alloc_contig_pages(1UL << try_order, gfp, NUMA_NO_NODE, NULL)' "$BACKING_SRC"
grep -qF '__free_page(nth_page(chunk->base, i));' "$BACKING_SRC"
! grep -qF 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$BACKING_SRC"
grep -qF 'gh_rm_get_vmid(rm, &self_vmid)' "$QCOM_SRC"
grep -qF 'GH_QCOM_SCM pre_share self_vmid=' "$QCOM_SRC"
grep -qF 'GH_QCOM_SCM post_reclaim self_vmid=' "$QCOM_SRC"
grep -qF 'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' "$QCOM_SRC"
grep -qF 'EXPORT_SYMBOL_GPL(gh_rm_get_vmid);' "$RM_RPC"
grep -Eq '^[[:space:]]*gh_rm_get_vmid[[:space:]]*$' "$ABI_LIST"
grep -qF 'qcom_scm_assign_mem' "$QCOM_SCM_HEADER"
grep -qF 'obj-m += gunyah_qcom.o # e3q vendor_boot test module; not packaged by AnyKernel' "$GUNYAH_MAKEFILE"
grep -qF 'qcom-scm.o # e3q vendor_boot test dependency; not packaged by AnyKernel' "$FIRMWARE_MAKEFILE"
grep -Eq '^qcom-scm-objs[[:space:]]*\+=[[:space:]]*qcom_scm\.o[[:space:]]+qcom_scm-smc\.o[[:space:]]+qcom_scm-legacy\.o' "$FIRMWARE_MAKEFILE"
grep -qF '"drivers/firmware/qcom-scm.ko",' "$MODULES_BZL"
grep -qF '"drivers/virt/gunyah/gunyah_qcom.ko",' "$MODULES_BZL"

echo 'e3q Gunyah 35088 preflight complete: 8192 guard + bounded RAM + SCM VMID mapping + additive KMI allowance + safe teardown + Kleaf test-module outputs'
