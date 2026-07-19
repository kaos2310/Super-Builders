#!/bin/bash
set -euo pipefail

FRAGMENT_SRC="${1:?}"
FRAGMENT_DST="${2:?}"
DEFCONFIG="${3:?}"
shift 3

ADD_SUSFS=false
ADD_OVERLAYFS=false
ADD_ZRAM=false
ADD_KPM=false
ADD_ZEROMOUNT=false
ADD_DROIDSPACES=false
USE_KLEAF=false

for arg in "$@"; do
  case "$arg" in
    --susfs) ADD_SUSFS=true ;;
    --overlayfs) ADD_OVERLAYFS=true ;;
    --zram) ADD_ZRAM=true ;;
    --kpm) ADD_KPM=true ;;
    --zeromount) ADD_ZEROMOUNT=true ;;
    --droidspaces) ADD_DROIDSPACES=true ;;
    --kleaf) USE_KLEAF=true ;;
  esac
done

extract_section() {
  awk "/^# \\[$1\\]/{found=1; next} /^# \\[/{found=0} found && NF" "$FRAGMENT_SRC"
}

extract_file_patch() {
  local source_patch="$1"
  local target_path="$2"
  local output_patch="$3"

  awk -v target="$target_path" '
    /^diff / {
      emit = ($0 ~ target "$" || $0 ~ target "[[:space:]]*$")
    }
    emit { print }
  ' "$source_patch" > "$output_patch"
}

extract_matching_hunks() {
  local source_patch="$1"
  local target_path="$2"
  local pattern="$3"
  local output_patch="$4"
  local file_patch="${output_patch}.file"

  extract_file_patch "$source_patch" "$target_path" "$file_patch"

  python3 - "$file_patch" "$pattern" "$output_patch" <<'PY'
from pathlib import Path
import re
import sys

source = Path(sys.argv[1])
pattern = re.compile(sys.argv[2])
out = Path(sys.argv[3])
lines = source.read_text().splitlines(keepends=True)

header = []
hunks = []
current = []
for line in lines:
    if line.startswith('@@ '):
        if current:
            hunks.append(current)
        current = [line]
    elif current:
        current.append(line)
    else:
        header.append(line)
if current:
    hunks.append(current)

selected = [h for h in hunks if pattern.search(''.join(h))]
if not selected:
    raise SystemExit(f'No matching hunks for pattern: {pattern.pattern}')
out.write_text(''.join(header + [line for h in selected for line in h]))
PY
}

apply_targeted_patch() {
  local common_tree="$1"
  local source_patch="$2"
  local target_path="$3"
  local temp_patch="$4"
  local hunk_pattern="${5:-}"

  if [[ -n "$hunk_pattern" ]]; then
    extract_matching_hunks "$source_patch" "$target_path" "$hunk_pattern" "$temp_patch"
  else
    extract_file_patch "$source_patch" "$target_path" "$temp_patch"
  fi

  if [[ ! -s "$temp_patch" ]]; then
    echo "::error::No patch section found for $target_path in $(basename "$source_patch")"
    return 1
  fi

  # --forward is mandatory. Without it, GNU patch may silently assume -R and
  # remove hooks that are already installed by the SukiSU reconciliation step.
  if patch -d "$common_tree" -p1 -F3 --forward --dry-run --batch < "$temp_patch" >/dev/null 2>&1; then
    echo "Applying official SUSFS base hooks: $target_path"
    patch -d "$common_tree" -p1 -F3 --forward --batch --no-backup-if-mismatch < "$temp_patch"
    return 0
  fi

  # A successful explicit reverse dry-run means the selected hunks are already
  # present. Never execute the reverse operation.
  if patch -d "$common_tree" -R -p1 -F3 --forward --dry-run --batch < "$temp_patch" >/dev/null 2>&1; then
    echo "Official SUSFS base hooks already present: $target_path"
    return 0
  fi

  echo "::error::Official SUSFS base hooks for $target_path neither apply forward nor are fully present"
  return 1
}

try_apply_targeted_patch() {
  local common_tree="$1"
  local source_patch="$2"
  local target_path="$3"
  local temp_patch="$4"
  local hunk_pattern="${5:-}"

  if [[ ! -f "$source_patch" ]]; then
    echo "::warning::Skip optional hook recovery for $target_path (missing patch: $source_patch)"
    return 0
  fi

  if apply_targeted_patch "$common_tree" "$source_patch" "$target_path" "$temp_patch" "$hunk_pattern"; then
    return 0
  fi

  echo "::warning::Optional hook recovery failed for $target_path from $(basename "$source_patch")"
  return 0
}

if $ADD_SUSFS; then
  VERSION_DIR="$(cd "$(dirname "$FRAGMENT_SRC")" && pwd)"
  COMMON_TREE="$(cd "$(dirname "$DEFCONFIG")/../../.." && pwd)"
  SUSFS_CLONE="${RUNNER_TEMP:-/tmp}/susfs4ksu"
  VERIFY_SCRIPT="$VERSION_DIR/build-helpers/verify-susfs-v2.2-procfs.sh"
  AUDIT_DIR="${RUNNER_TEMP:-/tmp}/sukisu-susfs-artifacts"
  TARGETED_DIR="${RUNNER_TEMP:-/tmp}/susfs-targeted-fixes"

  [[ -f "$VERIFY_SCRIPT" ]] || {
    echo "::error::Missing SUSFS Procfs verifier: $VERIFY_SCRIPT"
    exit 1
  }

  UPSTREAM_PATCH="$(find "$SUSFS_CLONE/kernel_patches" -maxdepth 1 -type f \
    \( -name '50_add_susfs_in_kernel-6.1.patch' \
       -o -name '50_add_susfs_in_gki-android14-6.1.patch' \
       -o -name '50_add_susfs_in_kernel*6.1*.patch' \) \
    -print -quit 2>/dev/null || true)"

  [[ -n "$UPSTREAM_PATCH" && -f "$UPSTREAM_PATCH" ]] || {
    echo "::error::Official Android 14 / 6.1 SUSFS base patch was not found under $SUSFS_CLONE/kernel_patches"
    find "$SUSFS_CLONE/kernel_patches" -maxdepth 2 -type f -name '*.patch' -print 2>/dev/null || true
    exit 1
  }

  echo "Using official SUSFS base patch: $UPSTREAM_PATCH"
  mkdir -p "$TARGETED_DIR" "$AUDIT_DIR"

  apply_targeted_patch "$COMMON_TREE" "$UPSTREAM_PATCH" \
    'fs/proc/task_mmu.c' "$TARGETED_DIR/task_mmu-base.patch"
  apply_targeted_patch "$COMMON_TREE" "$UPSTREAM_PATCH" \
    'fs/proc/base.c' "$TARGETED_DIR/proc-base-base.patch"

  # namei.c already contains unrelated SUS_PATH changes from the reconciliation.
  # Import only the Open Redirect insertion hunks to avoid colliding with them.
  apply_targeted_patch "$COMMON_TREE" "$UPSTREAM_PATCH" \
    'fs/namei.c' "$TARGETED_DIR/namei-open-redirect.patch" \
    'CONFIG_KSU_SUSFS_OPEN_REDIRECT|AS_FLAGS_OPEN_REDIRECT|susfs_get_redirected_path'

  chmod +x "$VERIFY_SCRIPT"
  if ! "$VERIFY_SCRIPT" "$COMMON_TREE" "$AUDIT_DIR/susfs-v2.2-procfs-audit.txt"; then
    echo "::warning::Initial SUSFS source audit failed; retrying with targeted hook recovery"
    ENHANCED_PATCH="$(find "$VERSION_DIR/SukiSU-Ultra/patches" -maxdepth 1 -type f \
      -name '51_enhanced_susfs-android14-6.1.patch' -print -quit 2>/dev/null || true)"

    try_apply_targeted_patch "$COMMON_TREE" "$UPSTREAM_PATCH" \
      'fs/susfs.c' "$TARGETED_DIR/susfs-open-redirect.patch" \
      'susfs_get_redirected_path|open_redirect'
    try_apply_targeted_patch "$COMMON_TREE" "$UPSTREAM_PATCH" \
      'include/linux/susfs.h' "$TARGETED_DIR/susfs-h-open-redirect.patch" \
      'susfs_get_redirected_path|open_redirect'

    try_apply_targeted_patch "$COMMON_TREE" "$ENHANCED_PATCH" \
      'fs/proc/base.c' "$TARGETED_DIR/proc-base-enhanced.patch" \
      'proc_map_files_readdir|AS_FLAGS_SUS_MAP|SUSFS_IS_INODE_SUS_MAP|susfs_is_current_proc_umounted_app'
    try_apply_targeted_patch "$COMMON_TREE" "$ENHANCED_PATCH" \
      'fs/namei.c' "$TARGETED_DIR/namei-open-redirect-enhanced.patch" \
      'CONFIG_KSU_SUSFS_OPEN_REDIRECT|AS_FLAGS_OPEN_REDIRECT|susfs_get_redirected_path|fake_pathname|set_nameidata\(&nd'

    "$VERIFY_SCRIPT" "$COMMON_TREE" "$AUDIT_DIR/susfs-v2.2-procfs-audit-retry.txt"
  fi
fi

extract_section "base" >> "$FRAGMENT_DST"
$ADD_SUSFS && extract_section "susfs" >> "$FRAGMENT_DST"
$ADD_OVERLAYFS && extract_section "overlayfs" >> "$FRAGMENT_DST"
$ADD_ZRAM && extract_section "zram" >> "$FRAGMENT_DST"
$ADD_KPM && extract_section "kpm" >> "$FRAGMENT_DST"
$ADD_ZEROMOUNT && extract_section "zeromount" >> "$FRAGMENT_DST"
$ADD_DROIDSPACES && extract_section "droidspaces" >> "$FRAGMENT_DST"

# Open Redirect is a permanent part of the Android 14 / 6.1 SUSFS build.
if $ADD_SUSFS; then
  sed -i '/^CONFIG_KSU_SUSFS_OPEN_REDIRECT=/d' "$FRAGMENT_DST"
  echo 'CONFIG_KSU_SUSFS_OPEN_REDIRECT=y' >> "$FRAGMENT_DST"

  if ! grep -Rqx 'config KSU_SUSFS_OPEN_REDIRECT' \
      "$COMMON_TREE" "${KSU_DIR:+$(dirname "$COMMON_TREE")/$KSU_DIR}" \
      --include='Kconfig*' 2>/dev/null; then
    echo "::error::SUSFS Open Redirect Kconfig symbol is missing"
    exit 1
  fi

  if [[ -n "${ARTIFACT_BASE:-}" ]]; then
    ARTIFACT_BASE="${ARTIFACT_BASE%-OpenRedirect-Test}"
    echo "ARTIFACT_BASE=$ARTIFACT_BASE" >> "${GITHUB_ENV:-/dev/null}"
  fi
  if [[ -n "${FILE_NAME:-}" ]]; then
    FILE_NAME="${FILE_NAME%-OpenRedirect-Test}"
    echo "FILE_NAME=$FILE_NAME" >> "${GITHUB_ENV:-/dev/null}"
  fi
fi

# dedup fragment: last-wins per CONFIG_ key
tac "$FRAGMENT_DST" | awk -F= '/^CONFIG_/{if(seen[$1]++)next} {print}' | tac > "${FRAGMENT_DST}.tmp"
mv "${FRAGMENT_DST}.tmp" "$FRAGMENT_DST"

if $ADD_SUSFS; then
  grep -qx 'CONFIG_KSU_SUSFS_OPEN_REDIRECT=y' "$FRAGMENT_DST" || {
    echo "::error::Open Redirect was not retained in the assembled fragment"
    exit 1
  }
fi

if $USE_KLEAF; then
  sed -i 's/^\(CONFIG_[A-Za-z0-9_]*\)=n$/# \1 is not set/' "$FRAGMENT_DST"
else
  grep '=n$' "$FRAGMENT_DST" >> "$DEFCONFIG" 2>/dev/null || true
  sed -i '/=n$/d' "$FRAGMENT_DST"
  cat "$FRAGMENT_DST" >> "$DEFCONFIG"
fi

if $ADD_ZRAM; then
  sed -i 's/CONFIG_ZRAM=m/CONFIG_ZRAM=y/g' "$DEFCONFIG" 2>/dev/null || true
  sed -i 's/CONFIG_ZSMALLOC=m/CONFIG_ZSMALLOC=y/g' "$DEFCONFIG" 2>/dev/null || true
fi

if ! $USE_KLEAF; then
  tac "$DEFCONFIG" | awk -F= '/^CONFIG_/{if(seen[$1]++)next} {print}' | tac > "${DEFCONFIG}.tmp"
  mv "${DEFCONFIG}.tmp" "$DEFCONFIG"
fi
