#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-vm-metadata-allocation.sh <kernel-tree>}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKING_HELPER="$SCRIPT_DIR/apply-e3q-gunyah-cma-compat.sh"

# Preserve the exact already-tested memshare/IRQFD diagnostics. The new backing
# allocator changes only how crosvm obtains physically clustered userspace RAM;
# the 8192 safety guard and Samsung Gunyah VM start path remain unchanged.
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

test -s "$BACKING_HELPER" || {
  echo "FATAL: Gunyah bounded-backing helper missing: $BACKING_HELPER" >&2
  exit 1
}

bash "$BASE_HELPER" "$KERNEL_TREE"
bash "$BACKING_HELPER" "$KERNEL_TREE"

VM_TARGET="$KERNEL_TREE/drivers/virt/gunyah/vm_mgr.c"
MAKEFILE="$KERNEL_TREE/drivers/virt/gunyah/Makefile"
UAPI="$KERNEL_TREE/include/uapi/linux/gunyah.h"
BACKING_SRC="$KERNEL_TREE/drivers/virt/gunyah/cma_compat.c"

grep -qF 'GH_DIAG mem_share refused' "$VM_TARGET"
grep -qF 'mapping->parcel.n_mem_entries > 8192' "$VM_TARGET"
grep -qF 'ret = -E2BIG;' "$VM_TARGET"
grep -qF 'case GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD:' "$VM_TARGET"
grep -qF 'cma_compat.o' "$MAKEFILE"
grep -qF 'GH_ANDROID_CREATE_CMA_COMPAT_MEM_FD' "$UAPI"
grep -qF '#define GH_EXTENT_MIN_ORDER 3U' "$BACKING_SRC"
grep -qF '#define GH_EXTENT_LIMIT 8192UL' "$BACKING_SRC"

# Verify both allocation paths and their matching teardown semantics. Keep these
# checks synchronized with apply-e3q-gunyah-cma-compat.sh so stale CI assertions
# cannot fail after a deliberate allocator refactor.
grep -qF 'alloc_pages(gfp, try_order)' "$BACKING_SRC"
grep -qF 'alloc_contig_pages(1UL << try_order, gfp, NUMA_NO_NODE, NULL)' "$BACKING_SRC"
grep -qF 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$BACKING_SRC"
grep -qF '__free_pages(chunk->base, chunk->order)' "$BACKING_SRC"
grep -qF 'clear_highpage(nth_page(base, i))' "$BACKING_SRC"
grep -qF 'cond_resched();' "$BACKING_SRC"
grep -qF 'vm_map_pages_zero(vma, buf->pages, nr_pages)' "$BACKING_SRC"

# Explicitly reject accidental regression to the impossible 256 MiB default-CMA
# allocation. On the S928B the linux,cma pool visible in boot logs is 32 MiB.
if grep -qF 'dma_alloc_from_contiguous(NULL' "$BACKING_SRC"; then
  echo 'FATAL: single-pool CMA allocation reintroduced into e3q guest backing' >&2
  exit 1
fi

echo 'e3q Gunyah bounded-extent backing layered on exact memshare-guard baseline (buddy + alloc_contig_pages verified)'
