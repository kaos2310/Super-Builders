#!/bin/bash
set -euo pipefail

COMMON="${1:?kernel common tree is required}"
KSU_ROOT="${2:?KernelSU root is required}"
SOURCE_PATCH="${3:?enhanced SUSFS patch is required}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BRIDGE="$SCRIPT_DIR/apply-enhanced-susfs-v2.2-bridge.sh"
SANITIZER="$SCRIPT_DIR/sanitize-sukisu-40901-common-hooks.py"
SETUID_NORMALIZER="$SCRIPT_DIR/normalize-sukisu-40901-setuid-susfs.py"
SUCOMPAT_NORMALIZER="$SCRIPT_DIR/normalize-sukisu-40901-sucompat.py"
KBUILD_NORMALIZER="$SCRIPT_DIR/normalize-sukisu-40901-kbuild.py"

[[ -f "$BRIDGE" ]] || {
  echo "::error::Pinned SukiSU/SUSFS bridge helper is missing: $BRIDGE"
  exit 1
}
[[ -f "$SANITIZER" ]] || {
  echo "::error::SukiSU 40901 common-hook sanitizer is missing: $SANITIZER"
  exit 1
}
[[ -f "$SETUID_NORMALIZER" ]] || {
  echo "::error::SukiSU 40901 setuid/SUSFS normalizer is missing: $SETUID_NORMALIZER"
  exit 1
}
[[ -f "$SUCOMPAT_NORMALIZER" ]] || {
  echo "::error::SukiSU 40901 native sucompat normalizer is missing: $SUCOMPAT_NORMALIZER"
  exit 1
}
[[ -f "$KBUILD_NORMALIZER" ]] || {
  echo "::error::SukiSU 40901 Kbuild normalizer is missing: $KBUILD_NORMALIZER"
  exit 1
}

chmod +x "$BRIDGE"
"$BRIDGE" "$COMMON" "$KSU_ROOT" "$SOURCE_PATCH"

echo "Reconciling legacy generic KernelSU/SUSFS hooks before ZeroMount..."
python3 "$SANITIZER" "$COMMON" "$KSU_ROOT"
python3 "$SETUID_NORMALIZER" "$KSU_ROOT"
python3 "$SUCOMPAT_NORMALIZER" "$KSU_ROOT"
python3 "$KBUILD_NORMALIZER" "$KSU_ROOT"

echo "Enhanced SUSFS integration and SukiSU 40901 pre-ZeroMount reconciliation complete."
