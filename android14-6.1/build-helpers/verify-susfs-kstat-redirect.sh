#!/bin/bash
set -euo pipefail

KERNEL_ROOT="${1:?kernel root}"
COMMON_TREE="${2:?common kernel tree}"
KSU_TREE="${3:?SukiSU tree}"
CONFIG_FILE="${4:?final kernel config}"

KCONFIG="$COMMON_TREE/fs/Kconfig"
SUSFS_DEF="$COMMON_TREE/include/linux/susfs_def.h"
SUSFS_HEADER="$COMMON_TREE/include/linux/susfs.h"
SUSFS_SOURCE="$COMMON_TREE/fs/susfs.c"
DISPATCH_SOURCE="$KSU_TREE/kernel/supercall/dispatch.c"

for path in \
  "$CONFIG_FILE" \
  "$KCONFIG" \
  "$SUSFS_DEF" \
  "$SUSFS_HEADER" \
  "$SUSFS_SOURCE" \
  "$DISPATCH_SOURCE"; do
  [[ -f "$path" ]] || {
    echo "::error::Full SUSFS kstat redirect audit input is missing: $path"
    exit 1
  }
done

grep -qx 'CONFIG_KSU_SUSFS_SUS_KSTAT=y' "$CONFIG_FILE"
grep -qx 'CONFIG_KSU_SUSFS_SUS_KSTAT_REDIRECT=y' "$CONFIG_FILE"

python3 - "$KCONFIG" "$SUSFS_DEF" "$SUSFS_HEADER" "$SUSFS_SOURCE" \
  "$DISPATCH_SOURCE" <<'PY'
from pathlib import Path
import re
import sys

kconfig_path, def_path, header_path, source_path, dispatch_path = map(
    Path, sys.argv[1:]
)
kconfig = kconfig_path.read_text(encoding="utf-8")
susfs_def = def_path.read_text(encoding="utf-8")
header = header_path.read_text(encoding="utf-8")
source = source_path.read_text(encoding="utf-8")
dispatch = dispatch_path.read_text(encoding="utf-8")

kconfig_match = re.search(
    r"^config KSU_SUSFS_SUS_KSTAT_REDIRECT\n(?P<body>.*?)(?=^config |^endmenu)",
    kconfig,
    re.MULTILINE | re.DOTALL,
)
if not kconfig_match:
    raise SystemExit("KSTAT redirect Kconfig block is missing")
kconfig_body = kconfig_match.group("body")
for marker in (
    "depends on KSU_SUSFS_SUS_KSTAT",
    "default y",
):
    if marker not in kconfig_body:
        raise SystemExit(f"KSTAT redirect Kconfig is incomplete: {marker}")

if not re.search(
    r"^#define CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT\s+0x55573$",
    susfs_def,
    re.MULTILINE,
):
    raise SystemExit("KSTAT redirect command ID 0x55573 is missing")

struct_match = re.search(
    r"struct st_susfs_sus_kstat_redirect\s*\{(?P<body>.*?)\n\};",
    header,
    re.DOTALL,
)
if not struct_match:
    raise SystemExit("KSTAT redirect userspace structure is missing")
struct_body = struct_match.group("body")
for field in (
    "virtual_pathname",
    "real_pathname",
    "spoofed_ino",
    "spoofed_dev",
    "spoofed_nlink",
    "spoofed_size",
    "spoofed_atime_tv_sec",
    "spoofed_mtime_tv_sec",
    "spoofed_ctime_tv_sec",
    "spoofed_blksize",
    "spoofed_blocks",
    "err",
):
    if field not in struct_body:
        raise SystemExit(f"KSTAT redirect structure field is missing: {field}")

function_start = source.find("void susfs_add_sus_kstat_redirect(")
if function_start < 0:
    raise SystemExit("KSTAT redirect implementation is missing")
function_end = source.find(
    "#endif // #ifdef CONFIG_KSU_SUSFS_SUS_KSTAT_REDIRECT", function_start
)
if function_end < 0:
    raise SystemExit("KSTAT redirect implementation guard is unterminated")
function = source[function_start:function_end]

# A complete redirect must resolve and mark both sides, register the real inode,
# optionally register a distinct virtual inode, serialize the shared hash table,
# and report the result to the caller.
for marker in (
    "kern_path(info.virtual_pathname",
    "kern_path(info.real_pathname",
    "set_bit(AS_FLAGS_SUS_KSTAT, &inode_virtual->i_mapping->flags)",
    "set_bit(AS_FLAGS_SUS_KSTAT, &inode_real->i_mapping->flags)",
    "new_entry->target_ino = inode_real->i_ino",
    "virtual_entry->target_ino = virtual_ino",
    "hash_add_rcu(SUS_KSTAT_HLIST, &new_entry->node, new_entry->target_ino)",
    "hash_add_rcu(SUS_KSTAT_HLIST, &virtual_entry->node, virtual_ino)",
    "mutex_lock(&susfs_mutex_lock_sus_kstat)",
    "mutex_unlock(&susfs_mutex_lock_sus_kstat)",
    "copy_to_user(",
):
    if marker not in function:
        raise SystemExit(f"KSTAT redirect implementation is incomplete: {marker}")
if "spin_lock(&susfs_spin_lock_sus_kstat)" in function:
    raise SystemExit("KSTAT redirect still uses the obsolete v2.1 spinlock")

if 'copy_config_to_buf("CONFIG_KSU_SUSFS_SUS_KSTAT_REDIRECT\\n"' not in source:
    raise SystemExit("KSTAT redirect is missing from the SUSFS feature report")

dispatch_match = re.search(
    r"case CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT:\s*\{?\s*"
    r"susfs_add_sus_kstat_redirect\(arg\);\s*return 0;",
    dispatch,
)
if not dispatch_match:
    raise SystemExit("SukiSU KSTAT redirect supercall dispatch is incomplete")
guard_start = dispatch.rfind(
    "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT_REDIRECT", 0, dispatch_match.start()
)
guard_end = dispatch.find("#endif", dispatch_match.end())
closed_before_case = (
    guard_start >= 0
    and dispatch.find("#endif", guard_start, dispatch_match.start()) >= 0
)
if guard_start < 0 or guard_end < 0 or closed_before_case:
    raise SystemExit("SukiSU KSTAT redirect dispatch is not config-guarded")

print("Verified complete SUSFS kstat redirect source and SukiSU dispatch")
PY

if command -v llvm-nm >/dev/null 2>&1; then
  NM_BIN="$(command -v llvm-nm)"
elif command -v nm >/dev/null 2>&1; then
  NM_BIN="$(command -v nm)"
else
  echo "::error::Neither llvm-nm nor nm is available"
  exit 1
fi

VMLINUX_CANDIDATES=(
  "$KERNEL_ROOT/out/android14-6.1/dist/vmlinux"
  "$KERNEL_ROOT/bazel-bin/common/kernel_aarch64/vmlinux"
  "$KERNEL_ROOT/bazel-bin/common/kernel_aarch64_dist/vmlinux"
)
while IFS= read -r candidate; do
  VMLINUX_CANDIDATES+=("$candidate")
done < <(find -L "$KERNEL_ROOT/bazel-bin/common" "$KERNEL_ROOT/out/android14-6.1" \
  -type f -name vmlinux -print 2>/dev/null || true)

VMLINUX=""
NM_OUTPUT=""
for candidate in "${VMLINUX_CANDIDATES[@]}"; do
  [[ -f "$candidate" ]] || continue
  if candidate_output="$("$NM_BIN" -n --defined-only "$candidate" 2>/dev/null | \
      awk '$NF == "susfs_add_sus_kstat_redirect" { print }')" && \
      [[ -n "$candidate_output" ]]; then
    VMLINUX="$candidate"
    NM_OUTPUT="$candidate_output"
    break
  fi
done
[[ -n "$VMLINUX" ]] || {
  echo "::error::No built vmlinux contains susfs_add_sus_kstat_redirect"
  find -L "$KERNEL_ROOT/bazel-bin/common" "$KERNEL_ROOT/out/android14-6.1" \
    -type f -name vmlinux -print 2>/dev/null || true
  exit 1
}

mapfile -t NM_LINES <<< "$NM_OUTPUT"
[[ "${#NM_LINES[@]}" -eq 1 ]] || {
  echo "::error::Expected exactly one susfs_add_sus_kstat_redirect definition"
  printf '%s\n' "$NM_OUTPUT"
  exit 1
}
NM_TYPE="$(awk 'NR == 1 { print $(NF - 1) }' <<< "$NM_OUTPUT")"
[[ "$NM_TYPE" =~ ^[Tt]$ ]] || {
  echo "::error::susfs_add_sus_kstat_redirect is not executable text (nm type: $NM_TYPE)"
  printf '%s\n' "$NM_OUTPUT"
  exit 1
}

echo "Verified CONFIG_KSU_SUSFS_SUS_KSTAT_REDIRECT=y and compiled symbol in ${VMLINUX#"$KERNEL_ROOT/"}"
