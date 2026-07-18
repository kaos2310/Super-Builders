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

apply_targeted_patch() {
  local common_tree="$1"
  local source_patch="$2"
  local target_path="$3"
  local temp_patch="$4"

  extract_file_patch "$source_patch" "$target_path" "$temp_patch"

  if [[ ! -s "$temp_patch" ]]; then
    echo "::error::No patch section found for $target_path"
    return 1
  fi

  if patch -d "$common_tree" -p1 -F3 --dry-run --batch < "$temp_patch" >/dev/null 2>&1; then
    echo "Applying targeted SUSFS fix: $target_path"
    patch -d "$common_tree" -p1 -F3 --batch --no-backup-if-mismatch < "$temp_patch"
    return 0
  fi

  if patch -d "$common_tree" -R -p1 -F3 --dry-run --batch < "$temp_patch" >/dev/null 2>&1; then
    echo "Targeted SUSFS fix already present: $target_path"
    return 0
  fi

  echo "::error::Targeted SUSFS fix for $target_path neither applies cleanly nor is fully present"
  return 1
}

if $ADD_SUSFS; then
  VERSION_DIR="$(cd "$(dirname "$FRAGMENT_SRC")" && pwd)"
  COMMON_TREE="$(cd "$(dirname "$DEFCONFIG")/../../.." && pwd)"
  FOLLOWUP_PATCH="$VERSION_DIR/SukiSU-Ultra/patches/51_enhanced_susfs-android14-6.1.patch"
  VERIFY_SCRIPT="$VERSION_DIR/build-helpers/verify-susfs-v2.2-procfs.sh"
  AUDIT_DIR="${RUNNER_TEMP:-/tmp}/sukisu-susfs-artifacts"
  TARGETED_DIR="${RUNNER_TEMP:-/tmp}/susfs-targeted-fixes"

  [[ -f "$FOLLOWUP_PATCH" ]] || {
    echo "::error::Missing SUSFS follow-up patch: $FOLLOWUP_PATCH"
    exit 1
  }
  [[ -f "$VERIFY_SCRIPT" ]] || {
    echo "::error::Missing SUSFS Procfs verifier: $VERIFY_SCRIPT"
    exit 1
  }

  mkdir -p "$TARGETED_DIR" "$AUDIT_DIR"

  # The SukiSU reconciliation installs SUSFS core files and registration paths,
  # but its current script does not install all Android 14 / 6.1 Procfs readers
  # or the complete Open Redirect lookup path. Applying the entire enhanced
  # patch collides with unrelated namespace and hardening changes, so import
  # only the four source-file sections required by the runtime failures.
  apply_targeted_patch "$COMMON_TREE" "$FOLLOWUP_PATCH" \
    'fs/proc/task_mmu.c' "$TARGETED_DIR/task_mmu.patch"
  apply_targeted_patch "$COMMON_TREE" "$FOLLOWUP_PATCH" \
    'fs/proc/base.c' "$TARGETED_DIR/proc-base.patch"
  apply_targeted_patch "$COMMON_TREE" "$FOLLOWUP_PATCH" \
    'fs/namei.c' "$TARGETED_DIR/namei.patch"
  apply_targeted_patch "$COMMON_TREE" "$FOLLOWUP_PATCH" \
    'fs/susfs.c' "$TARGETED_DIR/susfs.patch"

  chmod +x "$VERIFY_SCRIPT"
  "$VERIFY_SCRIPT" "$COMMON_TREE" "$AUDIT_DIR/susfs-v2.2-procfs-audit.txt"
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
