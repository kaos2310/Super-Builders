#!/bin/bash
set -euo pipefail

COMMON="${1:?kernel common tree is required}"
KSU_ROOT="${2:?KernelSU root is required}"
SOURCE_PATCH="${3:?enhanced SUSFS patch is required}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BRIDGE="$SCRIPT_DIR/apply-enhanced-susfs-v2.2-bridge.sh"
OPEN_KMI_NORMALIZER="$SCRIPT_DIR/normalize-susfs-open-kmi.py"
SANITIZER="$SCRIPT_DIR/sanitize-sukisu-40901-common-hooks.py"
SETUID_NORMALIZER="$SCRIPT_DIR/normalize-sukisu-40901-setuid-susfs.py"
SUCOMPAT_NORMALIZER="$SCRIPT_DIR/normalize-sukisu-40901-sucompat.py"
BOOT_EVENT_NORMALIZER="$SCRIPT_DIR/normalize-sukisu-40901-boot-event.py"
NATIVE_POLICY_NORMALIZER="$SCRIPT_DIR/normalize-sukisu-40901-native-policy.py"
KBUILD_NORMALIZER="$SCRIPT_DIR/normalize-sukisu-40901-kbuild.py"

[[ -f "$BRIDGE" ]] || {
  echo "::error::Pinned SukiSU/SUSFS bridge helper is missing: $BRIDGE"
  exit 1
}
[[ -f "$OPEN_KMI_NORMALIZER" ]] || {
  echo "::error::SUSFS fs/open.c KMI normalizer is missing: $OPEN_KMI_NORMALIZER"
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
[[ -f "$BOOT_EVENT_NORMALIZER" ]] || {
  echo "::error::SukiSU 40901 boot-event normalizer is missing: $BOOT_EVENT_NORMALIZER"
  exit 1
}
[[ -f "$NATIVE_POLICY_NORMALIZER" ]] || {
  echo "::error::SukiSU 40901 native policy normalizer is missing: $NATIVE_POLICY_NORMALIZER"
  exit 1
}
[[ -f "$KBUILD_NORMALIZER" ]] || {
  echo "::error::SukiSU 40901 Kbuild normalizer is missing: $KBUILD_NORMALIZER"
  exit 1
}

chmod +x "$BRIDGE"
"$BRIDGE" "$COMMON" "$KSU_ROOT" "$SOURCE_PATCH"

# The enhanced patch adds the SUSFS umbrella header to fs/open.c. Keep the
# enhanced hidden-name/unicode hooks, but restore the narrow include surface
# required by Samsung's stock nonseekable_open() genksyms CRC.
python3 "$OPEN_KMI_NORMALIZER" "$COMMON"

echo "Reconciling legacy generic KernelSU/SUSFS hooks before ZeroMount..."
python3 "$SANITIZER" "$COMMON" "$KSU_ROOT"
python3 "$SETUID_NORMALIZER" "$KSU_ROOT"
python3 "$SUCOMPAT_NORMALIZER" "$KSU_ROOT"
python3 "$BOOT_EVENT_NORMALIZER" "$KSU_ROOT"
python3 "$NATIVE_POLICY_NORMALIZER" "$KSU_ROOT"
python3 "$KBUILD_NORMALIZER" "$KSU_ROOT"

echo "Enhanced SUSFS integration and SukiSU 40901 pre-ZeroMount reconciliation complete."
