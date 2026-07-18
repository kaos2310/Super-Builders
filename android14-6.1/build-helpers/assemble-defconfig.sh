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

if $ADD_SUSFS; then
  VERSION_DIR="$(cd "$(dirname "$FRAGMENT_SRC")" && pwd)"
  COMMON_TREE="$(cd "$(dirname "$DEFCONFIG")/../../.." && pwd)"
  VERIFY_SCRIPT="$VERSION_DIR/build-helpers/verify-susfs-v2.2-procfs.sh"
  AUDIT_DIR="${RUNNER_TEMP:-/tmp}/sukisu-susfs-artifacts"

  [[ -f "$VERIFY_SCRIPT" ]] || {
    echo "::error::Missing SUSFS Procfs verifier: $VERIFY_SCRIPT"
    exit 1
  }

  # The SukiSU reconciliation step already applies the selected upstream SUSFS
  # source tree. Do not stack the repository's large enhanced patch on top of
  # that tree: it targets a different baseline and can be partly present while
  # failing both forward and reverse dry-runs. Audit the reconciled tree instead.
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

  # Remove the obsolete test-build suffix from names already created earlier.
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
