#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common kernel tree}"
KSU_TREE="${2:?KernelSU tree}"

# This stage is deliberately read-only. SukiSU 40901 lifecycle, dispatcher,
# app-profile and supercall semantics are already restored and validated by
# apply-enhanced-susfs-v2.2-core.sh. Here we validate only the post-ZeroMount
# source state plus the absence of the generic direct hooks that conflict with
# SukiSU 40901's native hook manager.

[[ -d "$COMMON_TREE" ]] || {
  echo "::error::Kernel common tree not found: $COMMON_TREE"
  exit 1
}
[[ -d "$KSU_TREE" ]] || {
  echo "::error::KernelSU tree not found: $KSU_TREE"
  exit 1
}

require_absent() {
  local relative="$1"
  local needle="$2"
  local path="$COMMON_TREE/$relative"
  [[ -f "$path" ]] || {
    echo "::error::Kernel source is missing while checking SukiSU 40901 reconciliation: $relative"
    exit 1
  }
  if grep -qF "$needle" "$path"; then
    echo "::error::Generic KernelSU/SUSFS direct hook survived SukiSU 40901 reconciliation: $relative: $needle"
    exit 1
  fi
}

# These callbacks belong to older direct-hook KernelSU/SUSFS layouts. The
# pinned SukiSU 40901 tree owns the equivalent syscall paths natively.
for token in \
  'ksu_handle_execveat(&fd, &filename' \
  'ksu_handle_execveat_sucompat(&fd, &filename' \
  'ksu_su_compat_enabled' \
  'susfs_is_sus_su_hooks_enabled' \
  'susfs_is_current_proc_no_su()' \
  'susfs_is_sdcard_android_data_not_decrypted'; do
  require_absent fs/exec.c "$token"
done

for spec in \
  'fs/open.c|ksu_handle_faccessat' \
  'fs/open.c|susfs_is_sus_su_hooks_enabled' \
  'fs/read_write.c|ksu_is_init_rc_hook_enabled' \
  'fs/read_write.c|ksu_handle_sys_read' \
  'fs/read_write.c|ksu_handle_vfs_read' \
  'fs/read_write.c|susfs_is_sus_su_hooks_enabled' \
  'fs/stat.c|ksu_is_init_rc_hook_enabled' \
  'fs/stat.c|ksu_handle_vfs_fstat' \
  'fs/stat.c|ksu_handle_stat' \
  'fs/stat.c|susfs_is_sus_su_hooks_enabled' \
  'kernel/sys.c|ksu_handle_setresuid(' \
  'kernel/sys.c|susfs_is_sus_su_hooks_enabled' \
  'drivers/input/input.c|ksu_is_input_hook_enabled' \
  'drivers/input/input.c|ksu_handle_input_handle_event('; do
  rel=${spec%%|*}
  token=${spec#*|}
  require_absent "$rel" "$token"
done

# The SUSFS setuid marker is retained in SukiSU's native setuid hook. Its
# is_zygote() dependency must remain explicit after the bridge repair.
SETUID_HOOK="$KSU_TREE/kernel/hook/setuid_hook.c"
if [[ -f "$SETUID_HOOK" ]] && grep -qF 'susfs_set_current_proc_umounted();' "$SETUID_HOOK"; then
  grep -qF '#include "selinux/selinux.h"' "$SETUID_HOOK" || {
    echo "::error::SukiSU setuid SUSFS marker lacks explicit selinux/selinux.h dependency"
    exit 1
  }
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

# Keep the exact post-ZeroMount assertions that were already proven by the
# build-capable #105 lineage.
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

# These adapter semantics are installed and fail-closed validated in Step 19.
# Recheck only the compatibility ABI that ZeroMount consumes after its patch.
for needle in \
  'ksu_susfs_ack_deprecated_external_dir' \
  'ksu_susfs_dispatch_path_compat' \
  'case CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT:' \
  'case CMD_SUSFS_SET_ANDROID_DATA_ROOT_PATH:' \
  'case CMD_SUSFS_SET_SDCARD_ROOT_PATH:'; do
  grep -RqF "$needle" "$KSU_TREE" || {
    echo "::error::ZeroMount/SUSFS dispatcher compatibility is missing after ZeroMount: $needle"
    exit 1
  }
done

# The legacy ZeroMount maps hook overlaps SUSFS show_map_vma() and caused a
# real apexd Oops on e3q. SUSFS SUS_MAP supplies map hiding, so this duplicate
# task_mmu hook must stay absent.
if grep -qF 'zeromount_spoof_mmap_metadata' "$COMMON_TREE/fs/proc/task_mmu.c"; then
  echo "::error::Unsafe duplicate ZeroMount task_mmu hook was reintroduced"
  exit 1
fi

echo "Verified post-ZeroMount source integrity, SukiSU 40901 direct-hook cleanup, SUSFS ${SUSFS_EXPECTED_VERSION:-pinned} compatibility, and safe task_mmu integration (read-only)"
