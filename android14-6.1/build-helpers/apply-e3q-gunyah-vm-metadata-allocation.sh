#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-vm-metadata-allocation.sh <kernel-tree>}"
VM_TARGET="$KERNEL_TREE/drivers/virt/gunyah/vm_mgr.c"

# Keep the exact, already device-tested e3q Gunyah compatibility transform as
# the immutable base.  This branch adds only the mem-share safety guard below;
# the grouped IRQFD fix, kvcalloc metadata fix, and GH_DIAG markers therefore
# remain byte-for-byte sourced from the last known-good kernel branch.
BASE_COMMIT="def60b7761847bc19c69b4be983699db2fe53f3a"
BASE_URL="https://raw.githubusercontent.com/kaos2310/Super-Builders/${BASE_COMMIT}/android14-6.1/build-helpers/apply-e3q-gunyah-vm-metadata-allocation.sh"
BASE_HELPER="$(mktemp -t e3q-gunyah-base.XXXXXX.sh)"
trap 'rm -f "$BASE_HELPER"' EXIT

curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
  "$BASE_URL" -o "$BASE_HELPER"

grep -qF 'GH_DIAG mem_alloc enter' "$BASE_HELPER"
grep -qF 'GH_DIAG mem_share begin' "$BASE_HELPER"
grep -qF 'struct gh_irqfd_group {' "$BASE_HELPER"
grep -qF 'using edge-compatible semantics' "$BASE_HELPER"

bash "$BASE_HELPER" "$KERNEL_TREE"

test -f "$VM_TARGET" || {
  echo "FATAL: Gunyah VM manager not found after base patch: $VM_TARGET" >&2
  exit 1
}

python3 - "$VM_TARGET" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()

limit = 512
refuse_marker = "GH_DIAG mem_share refused"
begin_marker = "GH_DIAG mem_share begin"

if refuse_marker not in source:
    old = (
        '\t\tpr_info("GH_DIAG mem_share begin vmid=%u label=%u type=%u entries=%zu\\n",\n'
        '\t\t\tghvm->vmid, mapping->parcel.label,\n'
        '\t\t\t(unsigned int)mapping->share_type,\n'
        '\t\t\tmapping->parcel.n_mem_entries);\n'
    )
    new = (
        f'\t\tif (mapping->parcel.n_mem_entries > {limit}) {{\n'
        '\t\t\tpr_err("GH_DIAG mem_share refused vmid=%u label=%u type=%u entries=%zu limit=%u\\n",\n'
        '\t\t\t\tghvm->vmid, mapping->parcel.label,\n'
        '\t\t\t\t(unsigned int)mapping->share_type,\n'
        f'\t\t\t\tmapping->parcel.n_mem_entries, {limit}U);\n'
        '\t\t\tret = -E2BIG;\n'
        '\t\t\tgoto err;\n'
        '\t\t}\n\n'
        + old
    )
    if source.count(old) != 1:
        raise SystemExit(
            "FATAL: cannot place e3q Gunyah mem-share guard; "
            f"expected one GH_DIAG share marker, found {source.count(old)}"
        )
    source = source.replace(old, new, 1)

checks = {
    "single guard log": source.count(refuse_marker) == 1,
    "single existing begin log": source.count(begin_marker) == 1,
    "entry threshold": f"mapping->parcel.n_mem_entries > {limit}" in source,
    "bounded failure": "ret = -E2BIG;" in source,
    "guard precedes RM share diagnostics": source.index(refuse_marker) < source.index(begin_marker),
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("FATAL: incomplete Gunyah mem-share guard: " + ", ".join(failed))

path.write_text(source)
print(
    f"Applied e3q Gunyah mem-share watchdog guard to {path}: "
    f"refuse parcels with more than {limit} physical extents"
)
PY

grep -qF 'GH_DIAG mem_share refused' "$VM_TARGET"
grep -qF 'mapping->parcel.n_mem_entries > 512' "$VM_TARGET"
grep -qF 'ret = -E2BIG;' "$VM_TARGET"
grep -qF 'GH_DIAG mem_share begin' "$VM_TARGET"

echo 'e3q Gunyah mem-share guard verified: max_entries=512, failure=-E2BIG'
