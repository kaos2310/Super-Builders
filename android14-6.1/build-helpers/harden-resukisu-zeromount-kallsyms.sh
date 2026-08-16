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
    'susfs_starts_with(iter->name, "bb_bprm_set_creds.ksu_") ||\n\t\t\t'
    'susfs_starts_with(iter->name, "__initstub__kmod_kernelsu") ||\n\t\t\t'
    'susfs_starts_with(iter->name, "__initcall__kmod_kernelsu") ||\n\t\t\t'
)

if 'susfs_starts_with(iter->name, "setup_ksu_") ||' not in text:
    if text.count(insert_before) != 1:
        raise SystemExit("KSU kallsyms insertion anchor is not unique")
    text = text.replace(insert_before, extra_ksu + insert_before, 1)
else:
    # Upgrade an already-hardened tree with the remaining observed init/local symbols.
    upgrade_anchor = 'susfs_starts_with(iter->name, "anon_ksu_") ||'
    extra_remaining_ksu = (
        '\n\t\t\t' 'susfs_starts_with(iter->name, "bb_bprm_set_creds.ksu_") ||'
        '\n\t\t\t' 'susfs_starts_with(iter->name, "__initstub__kmod_kernelsu") ||'
        '\n\t\t\t' 'susfs_starts_with(iter->name, "__initcall__kmod_kernelsu") ||'
    )
    if 'susfs_starts_with(iter->name, "bb_bprm_set_creds.ksu_") ||' not in text:
        if text.count(upgrade_anchor) != 1:
            raise SystemExit("KSU kallsyms upgrade anchor is not unique")
        text = text.replace(upgrade_anchor, upgrade_anchor + extra_remaining_ksu, 1)

zm_anchor = 'susfs_starts_with(iter->name, "susfs_") ||'
zm_filters = (
    'susfs_starts_with(iter->name, "zeromount_") ||',
    'susfs_starts_with(iter->name, "__initstub__kmod_zeromount") ||',
    'susfs_starts_with(iter->name, "__initcall__kmod_zeromount") ||',
)
if zm_filters[0] not in text:
    if text.count(zm_anchor) != 1:
        raise SystemExit("ZeroMount kallsyms insertion anchor is not unique")
    text = text.replace(
        zm_anchor,
        zm_anchor + '\n\t\t\t' + '\n\t\t\t'.join(zm_filters),
        1,
    )
else:
    zm_upgrade_anchor = zm_filters[0]
    missing_zm = [needle for needle in zm_filters[1:] if needle not in text]
    if missing_zm:
        if text.count(zm_upgrade_anchor) != 1:
            raise SystemExit("ZeroMount kallsyms upgrade anchor is not unique")
        text = text.replace(
            zm_upgrade_anchor,
            zm_upgrade_anchor + ''.join('\n\t\t\t' + needle for needle in missing_zm),
            1,
        )

required = (
    'susfs_starts_with(iter->name, "setup_ksu_") ||',
    'susfs_starts_with(iter->name, "do_ksu_") ||',
    'susfs_starts_with(iter->name, "is_task_ksu_") ||',
    'susfs_starts_with(iter->name, "anon_ksu_") ||',
    'susfs_starts_with(iter->name, "bb_bprm_set_creds.ksu_") ||',
    'susfs_starts_with(iter->name, "__initstub__kmod_kernelsu") ||',
    'susfs_starts_with(iter->name, "__initcall__kmod_kernelsu") ||',
    'susfs_starts_with(iter->name, "zeromount_") ||',
    'susfs_starts_with(iter->name, "__initstub__kmod_zeromount") ||',
    'susfs_starts_with(iter->name, "__initcall__kmod_zeromount") ||',
)
missing = [needle for needle in required if text.count(needle) != 1]
if missing:
    raise SystemExit(f"kallsyms hardening audit failed: {missing}")

path.write_text(text, encoding="utf-8")
print("ReSukiSU kallsyms filter covers observed KSU normal/init/local symbol names")
print("ZeroMount kallsyms filter covers normal, initstub and initcall symbols")
print("Internal kallsyms lookup/export tables are unchanged; only /proc/kallsyms output is filtered")
PY
