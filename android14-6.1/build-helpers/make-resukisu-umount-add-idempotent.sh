#!/bin/bash
set -euo pipefail

KSU_TREE="${1:?KernelSU tree}"
TARGET="$KSU_TREE/kernel/supercall/dispatch.c"

[[ -f "$TARGET" ]] || {
  echo "::error::ReSukiSU dispatch source is unavailable: $TARGET"
  exit 1
}

python3 - "$TARGET" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

marker = 'cmd_manage_try_umount: %s is already here!'
if text.count(marker) != 1:
    raise SystemExit(f"Expected exactly one duplicate-umount marker, found {text.count(marker)}")

# Restrict the replacement to the duplicate-path branch. A repeated ADD does
# not alter the existing entry, so returning success makes the operation
# idempotent without changing the mount-list contents or ABI/KMI-visible types.
pattern = re.compile(
    r'(pr_info\("cmd_manage_try_umount: %s is already here!.*?'
    r'kfree\(new_entry->umountable\);\s*'
    r'kfree\(new_entry\);\s*)'
    r'return\s+-EEXIST\s*;',
    re.S,
)
replacement = r'\1return 0;'

if re.search(
    r'cmd_manage_try_umount: %s is already here!.*?return\s+0\s*;',
    text,
    re.S,
):
    print("ReSukiSU duplicate umount ADD is already idempotent")
else:
    text, count = pattern.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit(
            "Could not isolate the duplicate umount ADD -EEXIST return; source drifted"
        )

block_match = re.search(
    r'cmd_manage_try_umount: %s is already here!.*?return\s+([^-;][^;]*)\s*;',
    text,
    re.S,
)
if not block_match or block_match.group(1).strip() != '0':
    raise SystemExit("Duplicate umount ADD did not become idempotent")

path.write_text(text, encoding="utf-8")
print("ReSukiSU duplicate kernel umount ADD now returns success")
print("Existing mount-list entry and flags remain unchanged; only duplicate status becomes idempotent")
PY
