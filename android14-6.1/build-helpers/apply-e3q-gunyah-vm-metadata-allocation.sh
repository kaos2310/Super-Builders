#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-vm-metadata-allocation.sh <kernel-tree>}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CMA_HELPER="$SCRIPT_DIR/apply-e3q-gunyah-cma-compat.sh"

# Preserve the exact, already-tested memshare/IRQFD diagnostics from the
# parent experimental branch. The CMA experiment is layered after it so the
# 8192 safety guard and all GH_DIAG markers remain unchanged.
BASE_COMMIT="882a22c8e13e16661c90226ace6579fc001361f3"
BASE_URL="https://raw.githubusercontent.com/kaos2310/Super-Builders/${BASE_COMMIT}/android14-6.1/build-helpers/apply-e3q-gunyah-vm-metadata-allocation.sh"
BASE_HELPER="$(mktemp -t e3q-gunyah-memshare.XXXXXX.sh)"
trap 'rm -f "$BASE_HELPER"' EXIT

curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
  "$BASE_URL" -o "$BASE_HELPER"

grep -qF 'GH_DIAG mem_share refused' "$BASE_HELPER"
grep -qF 'mapping->parcel.n_mem_entries > 8192' "$BASE_HELPER"
grep -qF 'ret = -E2BIG;' "$BASE_HELPER"
grep -qF 'GH_DIAG rm_mem_share call begin' "$BASE_HELPER"
grep -qF 'using edge-compatible semantics' "$BASE_HELPER"

test -s "$CMA_HELPER" || {
  echo "FATAL: Gunyah CMA compatibility helper missing: $CMA_HELPER" >&2
  exit 1
}

bash "$BASE_HELPER" "$KERNEL_TREE"
bash "$CMA_HELPER" "$KERNEL_TREE"

VM_TARGET="$KERNEL_TREE/drivers/virt/gunyah/vm_mgr.c"
MAKEFILE="$KERNEL_TREE/drivers/virt/gunyah/Makefile"
UAPI="$KERNEL_TREE/include/uapi/linux/gunyah.h"
CMA_SRC="$KERNEL_TREE/drivers/virt/gunyah/cma_compat.c"

grep -qF 'GH_DIAG mem_share refused' "$VM_TARGET"
grep -qF 'mapping->parcel.n_mem_entries > 8192' "$VM_TARGET"
grep -qF 'ret = -E2BIG;' "$VM_TARGET"
grep -qF 'case GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD:' "$VM_TARGET"
grep -qF 'cma_compat.o' "$MAKEFILE"
grep -qF 'GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD' "$UAPI"
grep -qF 'dma_alloc_from_contiguous(NULL, count, 0, false)' "$CMA_SRC"

echo 'e3q Gunyah CMA experiment layered on exact memshare-guard baseline'