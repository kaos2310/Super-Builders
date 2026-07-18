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

apply_patch_once() {
  local common_tree="$1"
  local patch_file="$2"

  if patch -d "$common_tree" -p1 -F3 --dry-run --batch < "$patch_file" >/dev/null 2>&1; then
    echo "Applying $(basename "$patch_file")"
    patch -d "$common_tree" -p1 -F3 --batch --no-backup-if-mismatch < "$patch_file"
    return 0
  fi

  if patch -d "$common_tree" -R -p1 -F3 --dry-run --batch < "$patch_file" >/dev/null 2>&1; then
    echo "$(basename "$patch_file") is already applied"
    return 0
  fi

  echo "::error::$(basename "$patch_file") neither applies cleanly nor appears to be present"
  return 1
}

if $ADD_SUSFS; then
  VERSION_DIR="$(cd "$(dirname "$FRAGMENT_SRC")" && pwd)"
  COMMON_TREE="$(cd "$(dirname "$DEFCONFIG")/../../.." && pwd)"
  ENHANCED_PATCH="$VERSION_DIR/SukiSU-Ultra/patches/51_enhanced_susfs-android14-6.1.patch"
  VERIFY_SCRIPT="$VERSION_DIR/build-helpers/verify-susfs-v2.2-procfs.sh"
  AUDIT_DIR="${RUNNER_TEMP:-/tmp}/sukisu-susfs-artifacts"

  [[ -f "$ENHANCED_PATCH" ]] || {
    echo "::error::Missing enhanced SUSFS patch: $ENHANCED_PATCH"
    exit 1
  }
  [[ -f "$VERIFY_SCRIPT" ]] || {
    echo "::error::Missing SUSFS Procfs verifier: $VERIFY_SCRIPT"
    exit 1
  }

  # The upstream v2.2 base is installed earlier by the SukiSU reconciliation
  # step. Apply the maintained Android 14 / 6.1 follow-up containing the
  # Procfs/SUS_MAP fixes, including the unmounted-app guard and the maps,
  # smaps, pagemap, map_files and remote-memory filtering paths.
  apply_patch_once "$COMMON_TREE" "$ENHANCED_PATCH"

  mkdir -p "$AUDIT_DIR"
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

# dedup fragment: last-wins per CONFIG_ key
tac "$FRAGMENT_DST" | awk -F= '/^CONFIG_/{if(seen[$1]++)next} {print}' | tac > "${FRAGMENT_DST}.tmp"
mv "${FRAGMENT_DST}.tmp" "$FRAGMENT_DST"

if $USE_KLEAF; then
  # Kleaf applies fragment via --defconfig_fragment; don't touch gki_defconfig
  # Convert =n to "# is not set" format (Kleaf can't match =n against savedefconfig)
  sed -i 's/^\(CONFIG_[A-Za-z0-9_]*\)=n$/# \1 is not set/' "$FRAGMENT_DST"
else
  # Legacy build.sh doesn't merge fragments — configs must be in gki_defconfig
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
