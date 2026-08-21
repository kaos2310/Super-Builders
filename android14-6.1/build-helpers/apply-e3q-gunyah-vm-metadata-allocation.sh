#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-vm-metadata-allocation.sh <kernel-tree>}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_COMMIT="9bf8da21bb7e5891bb9b4ef917893a5792874608"
TMP_DIR="$(mktemp -d -t e3q-gunyah-35088.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

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
test -s "$FOLLOWUP" || { echo "FATAL: missing e3q Gunyah SCM follow-up helper: $FOLLOWUP" >&2; exit 1; }
bash "$FOLLOWUP" "$KERNEL_TREE"

GUNYAH_DIR="$KERNEL_TREE/drivers/virt/gunyah"
QCOM_SRC="$GUNYAH_DIR/gunyah_qcom.c"
BACKING_SRC="$GUNYAH_DIR/cma_compat.c"
MAKEFILE="$GUNYAH_DIR/Makefile"
VM_TARGET="$GUNYAH_DIR/vm_mgr.c"

grep -qF 'mapping->parcel.n_mem_entries > 8192' "$VM_TARGET"
grep -qF 'ret = -E2BIG;' "$VM_TARGET"
grep -qF 'alloc_contig_pages(1UL << try_order, gfp, NUMA_NO_NODE, NULL)' "$BACKING_SRC"
grep -qF '__free_page(nth_page(chunk->base, i));' "$BACKING_SRC"
! grep -qF 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$BACKING_SRC"
grep -qF 'gh_rm_get_vmid(rm, &self_vmid)' "$QCOM_SRC"
grep -qF 'GH_QCOM_SCM pre_share self_vmid=' "$QCOM_SRC"
grep -qF 'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' "$QCOM_SRC"
grep -qF 'obj-m += gunyah_qcom.o # e3q vendor_boot test module; not packaged by AnyKernel' "$MAKEFILE"

echo 'e3q Gunyah 35088 follow-up verified: bounded extents + SCM VMID mapping + patched vendor_boot test module target'
