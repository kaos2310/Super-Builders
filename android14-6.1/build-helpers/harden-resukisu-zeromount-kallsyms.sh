#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common tree}"
TARGET="$COMMON_TREE/kernel/kallsyms.c"

[[ -f "$TARGET" ]] || {
  echo "::error::kallsyms source is unavailable: $TARGET"
  exit 1
}

python3 - "$TARGET" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

base_marker = 'susfs_starts_with(iter->name, "ksu_") ||'
if base_marker not in text:
    raise SystemExit(
        "SUSFS kallsyms filter is missing; refusing to modify an unexpected kallsyms.c"
    )

insert_before = 'susfs_starts_with(iter->name, "is_ksu_") ||'
extra_ksu = (
    'susfs_starts_with(iter->name, "setup_ksu_") ||\n\t\t\t'
    'susfs_starts_with(iter->name, "do_ksu_") ||\n\t\t\t'
    'susfs_starts_with(iter->name, "is_task_ksu_") ||\n\t\t\t'
    'susfs_starts_with(iter->name, "anon_ksu_") ||\n\t\t\t'
)

if 'susfs_starts_with(iter->name, "setup_ksu_") ||' not in text:
    if text.count(insert_before) != 1:
        raise SystemExit("KSU kallsyms insertion anchor is not unique")
    text = text.replace(insert_before, extra_ksu + insert_before, 1)

zm_anchor = 'susfs_starts_with(iter->name, "susfs_") ||'
zm_filter = 'susfs_starts_with(iter->name, "zeromount_") ||'
if zm_filter not in text:
    if text.count(zm_anchor) != 1:
        raise SystemExit("ZeroMount kallsyms insertion anchor is not unique")
    text = text.replace(
        zm_anchor,
        zm_anchor + '\n\t\t\t' + zm_filter,
        1,
    )

required = (
    'susfs_starts_with(iter->name, "setup_ksu_") ||',
    'susfs_starts_with(iter->name, "do_ksu_") ||',
    'susfs_starts_with(iter->name, "is_task_ksu_") ||',
    'susfs_starts_with(iter->name, "anon_ksu_") ||',
    'susfs_starts_with(iter->name, "zeromount_") ||',
)
missing = [needle for needle in required if text.count(needle) != 1]
if missing:
    raise SystemExit(f"kallsyms hardening audit failed: {missing}")

path.write_text(text, encoding="utf-8")
print("ReSukiSU kallsyms filter extended for observed KSU symbol prefixes")
print("ZeroMount kallsyms filter enabled for zeromount_* symbols")
print("Internal kallsyms lookup/export tables are unchanged; only /proc/kallsyms output is filtered")
PY
