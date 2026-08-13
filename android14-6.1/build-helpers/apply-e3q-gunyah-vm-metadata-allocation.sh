#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-vm-metadata-allocation.sh <kernel-tree>}"
TARGET="$KERNEL_TREE/drivers/virt/gunyah/vm_mgr_mm.c"

test -f "$TARGET" || {
  echo "FATAL: Gunyah VM memory manager not found: $TARGET" >&2
  exit 1
}

python3 - "$TARGET" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
source = path.read_text()

if "int gh_vm_mem_alloc(" not in source:
    raise SystemExit(f"FATAL: gh_vm_mem_alloc() not found in {path}")

pages_old = re.compile(
    r"mapping->pages\s*=\s*kcalloc\(\s*mapping->npages\s*,\s*"
    r"sizeof\(\*mapping->pages\)\s*,\s*GFP_KERNEL_ACCOUNT\s*\);"
)
entries_old = re.compile(
    r"parcel->mem_entries\s*=\s*kcalloc\(\s*parcel->n_mem_entries\s*,\s*"
    r"sizeof\(parcel->mem_entries\[0\]\)\s*,\s*GFP_KERNEL_ACCOUNT\s*\);"
)

pages_new = (
    "mapping->pages = kvcalloc(mapping->npages, sizeof(*mapping->pages),\n"
    "\t\t\t\t  GFP_KERNEL_ACCOUNT);"
)
entries_new = (
    "parcel->mem_entries = kvcalloc(parcel->n_mem_entries,\n"
    "\t\t\t\t      sizeof(parcel->mem_entries[0]),\n"
    "\t\t\t\t      GFP_KERNEL_ACCOUNT);"
)

already_patched = (
    pages_old.search(source) is None
    and entries_old.search(source) is None
    and "mapping->pages = kvcalloc(" in source
    and "parcel->mem_entries = kvcalloc(" in source
)

if not already_patched:
    source, pages_count = pages_old.subn(pages_new, source)
    source, entries_count = entries_old.subn(entries_new, source)
    if pages_count != 1 or entries_count != 1:
        raise SystemExit(
            "FATAL: unexpected Gunyah allocation layout: "
            f"pages={pages_count}, mem_entries={entries_count}"
        )

if "#include <linux/slab.h>" not in source:
    marker = "#include <linux/mm.h>\n"
    if source.count(marker) != 1:
        raise SystemExit("FATAL: cannot place explicit linux/slab.h include")
    source = source.replace(marker, marker + "#include <linux/slab.h>\n", 1)

pages_free_count = source.count("kfree(mapping->pages);")
if pages_free_count:
    if pages_free_count != 2:
        raise SystemExit(
            f"FATAL: expected two mapping->pages frees, found {pages_free_count}"
        )
    source = source.replace("kfree(mapping->pages);", "kvfree(mapping->pages);")

entries_free_count = source.count("kfree(mapping->parcel.mem_entries);")
if entries_free_count:
    if entries_free_count != 1:
        raise SystemExit(
            "FATAL: expected one parcel mem_entries free, "
            f"found {entries_free_count}"
        )
    source = source.replace(
        "kfree(mapping->parcel.mem_entries);",
        "kvfree(mapping->parcel.mem_entries);",
    )

checks = {
    "pages kvcalloc": source.count("mapping->pages = kvcalloc(") == 1,
    "mem_entries kvcalloc": source.count("parcel->mem_entries = kvcalloc(") == 1,
    "pages kvfree": source.count("kvfree(mapping->pages);") == 2,
    "mem_entries kvfree": source.count("kvfree(mapping->parcel.mem_entries);") == 1,
    "legacy pages allocation removed": pages_old.search(source) is None,
    "legacy entries allocation removed": entries_old.search(source) is None,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("FATAL: incomplete Gunyah metadata fix: " + ", ".join(failed))

path.write_text(source)
print(f"Applied fragmentation-safe Gunyah VM metadata allocation fix to {path}")
PY

grep -qF 'mapping->pages = kvcalloc(' "$TARGET"
grep -qF 'parcel->mem_entries = kvcalloc(' "$TARGET"
test "$(grep -cF 'kvfree(mapping->pages);' "$TARGET")" -eq 2
test "$(grep -cF 'kvfree(mapping->parcel.mem_entries);' "$TARGET")" -eq 1

