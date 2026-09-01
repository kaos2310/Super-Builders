#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common kernel tree}"
KSU_TREE="${2:?KernelSU tree}"

[[ -d "$KSU_TREE" ]] || {
  echo "::error::KernelSU tree not found: $KSU_TREE"
  exit 1
}

# Finalize the SukiSU-specific port after the generic GKI SUSFS filesystem
# patch and ZeroMount have been applied. This removes only the generic direct
# KSU callbacks that conflict with SukiSU Ultra 40901's native hook manager.
if [[ -f "$KSU_TREE/.sukisu-ultra-source-pin" ]]; then
  FINALIZE="$GITHUB_WORKSPACE/android14-6.1/build-helpers/finalize-sukisu-40901-susfs-port.sh"
  chmod +x "$FINALIZE"
  "$FINALIZE" "$COMMON_TREE" "$KSU_TREE"
fi

require_source() {
  local relative="$1"
  local needle="$2"
  local path="$COMMON_TREE/$relative"
  [[ -f "$path" ]] || {
    echo "::error::ZeroMount/SUSFS source is missing: $relative"
    exit 1
  }
  grep -qF "$needle" "$path" || {
    echo "::error::ZeroMount/SUSFS hook is missing from $relative: $needle"
    exit 1
  }
}

require_source fs/Kconfig 'config ZEROMOUNT'
require_source fs/Makefile 'obj-$(CONFIG_ZEROMOUNT)'
require_source fs/zeromount.c 'zeromount_ioctl_add_rule'
require_source fs/zeromount.c 'zeromount_inject_dents64'
require_source fs/zeromount.c 'zeromount_is_uid_blocked'
require_source fs/zeromount.c 'zeromount_spoof_statfs'
require_source fs/zeromount.c 'kern_path(statfs_root, LOOKUP_FOLLOW, &root_path)'
require_source fs/zeromount.c '*buf = root_stats'
require_source fs/zeromount.c 'zeromount_spoof_xattr'
require_source include/linux/zeromount.h 'ZEROMOUNT_IOC_GET_STATUS'
require_source fs/namei.c 'zeromount_getname_hook'
require_source fs/readdir.c 'zeromount_inject_dents64'
require_source fs/d_path.c 'zeromount_get_static_vpath'
require_source fs/proc/base.c 'zeromount_get_static_vpath'
require_source fs/stat.c 'zeromount_stat_hook'
require_source fs/statfs.c 'zeromount_spoof_statfs'
require_source fs/xattr.c 'zeromount_spoof_xattr'
require_source fs/susfs.c 'susfs_add_sus_kstat_redirect'
require_source fs/susfs.c 'susfs_add_sus_map'

for needle in \
  'ksu_susfs_ack_deprecated_external_dir' \
  'case CMD_SUSFS_SET_ANDROID_DATA_ROOT_PATH:' \
  'case CMD_SUSFS_SET_SDCARD_ROOT_PATH:'; do
  grep -RqF "$needle" "$KSU_TREE" || {
    echo "::error::ZeroMount/SUSFS external-directory compatibility is missing: $needle"
    exit 1
  }
done

# The legacy ZeroMount maps hook overlaps SUSFS 2.2 show_map_vma() and caused
# a real apexd Oops on e3q. SUSFS SUS_MAP supplies map hiding, so the unsafe
# duplicate task_mmu hook must remain absent.
if grep -qF 'zeromount_spoof_mmap_metadata' "$COMMON_TREE/fs/proc/task_mmu.c"; then
  echo "::error::Unsafe duplicate ZeroMount task_mmu hook was reintroduced"
  exit 1
fi

# Verify the seven requested SukiSU 40901 rebase-sensitive files are still the
# exact baseline captured before SUSFS was applied.
if [[ -n "${SUKISU_REBASE_MANIFEST:-}" ]]; then
  AUDIT="$GITHUB_WORKSPACE/android14-6.1/build-helpers/audit-sukisu-40901-susfs-rebase.sh"
  chmod +x "$AUDIT"
  "$AUDIT" verify "$KSU_TREE" "$SUKISU_REBASE_MANIFEST"
fi

echo "Verified ZeroMount VFS hooks, SUSFS 2.2 native SukiSU ABI, 40901 rebase gate, and external-directory compatibility"
