#!/bin/bash
set -euo pipefail

COMMON="${1:?kernel common tree is required}"
KSU_ROOT="${2:?KernelSU root is required}"
SOURCE_PATCH="${3:?enhanced SUSFS patch is required}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CORE_HELPER="$SCRIPT_DIR/apply-enhanced-susfs-v2.2-core.sh"
SUSFS_TREE="${SUSFS_FOLDER:-}"

[[ -d "$COMMON" ]] || { echo "::error::Kernel common tree is missing: $COMMON"; exit 1; }
[[ -d "$KSU_ROOT" ]] || { echo "::error::SukiSU tree is missing: $KSU_ROOT"; exit 1; }
[[ -x "$CORE_HELPER" || -f "$CORE_HELPER" ]] || { echo "::error::Enhanced SUSFS core helper is missing: $CORE_HELPER"; exit 1; }
[[ -n "$SUSFS_TREE" && -d "$SUSFS_TREE" ]] || { echo "::error::Pinned SUSFS tree is unavailable (SUSFS_FOLDER=${SUSFS_TREE:-<unset>})"; exit 1; }

KSU_SUSFS_PATCH="$SUSFS_TREE/kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch"
[[ -s "$KSU_SUSFS_PATCH" ]] || { echo "::error::Pinned SUSFS KernelSU integration patch is missing: $KSU_SUSFS_PATCH"; exit 1; }

# ReSukiSU carried the SUSFS KernelSU-side dispatcher natively. SukiSU Ultra
# v4.2.0 (dev/release pin 85eb4a95...) does not: its userspace intentionally
# talks to SUSFS through reboot(2), and the SUSFS project supplies that kernel
# bridge in 10_enable_susfs_for_ksu.patch.  The old strict workflow only
# copied/applied the GKI-side 50_* patch, so the enhanced helper later had no
# ksu_handle_susfs_cmd()/kstat dispatch block to extend.
DISPATCH="$KSU_ROOT/kernel/supercall/dispatch.c"
if [[ -f "$DISPATCH" ]] && grep -qF 'int ksu_handle_susfs_cmd(' "$DISPATCH" && grep -qF 'CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY' "$DISPATCH"; then
  echo "Pinned SUSFS KernelSU-side integration already present in SukiSU tree."
else
  echo "Applying pinned SUSFS KernelSU-side integration to SukiSU Ultra..."
  if patch -d "$KSU_ROOT" -p1 -F3 --forward --batch --dry-run < "$KSU_SUSFS_PATCH"; then
    patch -d "$KSU_ROOT" -p1 -F3 --forward --batch --no-backup-if-mismatch < "$KSU_SUSFS_PATCH"
  elif patch -d "$KSU_ROOT" -R -p1 -F3 --forward --batch --dry-run < "$KSU_SUSFS_PATCH" >/dev/null 2>&1; then
    echo "Pinned SUSFS KernelSU-side integration is already applied."
  else
    echo "::error::Pinned SUSFS 2.3.0 KernelSU integration does not apply cleanly to the selected SukiSU tree."
    echo "::group::SUSFS KernelSU patch diagnostics"
    patch -d "$KSU_ROOT" -p1 -F3 --forward --batch --dry-run < "$KSU_SUSFS_PATCH" || true
    echo "::endgroup::"
    exit 1
  fi
fi

[[ -f "$DISPATCH" ]] || { echo "::error::SukiSU SUSFS dispatcher source is missing after integration: $DISPATCH"; exit 1; }
grep -qF 'int ksu_handle_susfs_cmd(' "$DISPATCH" || {
  echo "::error::Pinned SUSFS integration did not install ksu_handle_susfs_cmd() into SukiSU."
  exit 1
}
grep -qF 'CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY' "$DISPATCH" || {
  echo "::error::Pinned SUSFS integration did not install the SUS_KSTAT dispatch into SukiSU."
  exit 1
}

chmod +x "$CORE_HELPER"
exec "$CORE_HELPER" "$COMMON" "$KSU_ROOT" "$SOURCE_PATCH"
