#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common kernel tree}"
KSU_TREE="${2:?KernelSU tree}"

# Verification is intentionally read-only. SukiSU 40901 source reconciliation
# must complete before ZeroMount is applied.

[[ -d "$COMMON_TREE" ]] || {
  echo "::error::Kernel common tree not found: $COMMON_TREE"
  exit 1
}
[[ -d "$KSU_TREE" ]] || {
  echo "::error::KernelSU tree not found: $KSU_TREE"
  exit 1
}

# Fail before compilation if any generic KernelSU/SUSFS callback glue survived
# the pre-ZeroMount reconciliation stage.
for token in \
  'ksu_handle_execveat(&fd, &filename' \
  'ksu_handle_execveat_sucompat(&fd, &filename' \
  'ksu_su_compat_enabled' \
  'susfs_is_sus_su_hooks_enabled' \
  'susfs_is_current_proc_no_su()' \
  'susfs_is_sdcard_android_data_not_decrypted'; do
  if grep -qF "$token" "$COMMON_TREE/fs/exec.c"; then
    echo "::error::Generic SUSFS exec hook survived SukiSU 40901 cleanup: $token"
    exit 1
  fi
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
  'fs/stat.c|susfs_is_sus_su_hooks_enabled'; do
  rel=${spec%%|*}
  token=${spec#*|}
  if grep -qF "$token" "$COMMON_TREE/$rel"; then
    echo "::error::Generic SUSFS direct hook survived SukiSU 40901 cleanup: $rel: $token"
    exit 1
  fi
done

if grep -qF 'ksu_handle_setresuid(' "$COMMON_TREE/kernel/sys.c"; then
  echo "::error::Generic SUSFS setresuid hook survived SukiSU 40901 cleanup"
  exit 1
fi
if grep -qF 'susfs_is_sus_su_hooks_enabled' "$COMMON_TREE/kernel/sys.c"; then
  echo "::error::Generic SUS_SU setresuid guard survived SukiSU 40901 cleanup"
  exit 1
fi
if grep -qF 'ksu_is_input_hook_enabled' "$COMMON_TREE/drivers/input/input.c" || \
   grep -qF 'ksu_handle_input_handle_event(' "$COMMON_TREE/drivers/input/input.c"; then
  echo "::error::Generic SUSFS input hook survived SukiSU 40901 cleanup"
  exit 1
fi

# The setuid marker dependency is repaired before ZeroMount; verify only.
SETUID_HOOK="$KSU_TREE/kernel/hook/setuid_hook.c"
if [[ -f "$SETUID_HOOK" ]] && grep -qF 'susfs_set_current_proc_umounted();' "$SETUID_HOOK"; then
  if ! grep -qF '#include "selinux/selinux.h"' "$SETUID_HOOK"; then
    echo "::error::SukiSU setuid SUSFS marker lacks explicit selinux/selinux.h dependency"
    exit 1
  fi
fi

# Prove the native SukiSU 40901 execution paths that replace the removed glue.
grep -qF 'new_uid != WEBVIEW_ZYGOTE_UID' "$KSU_TREE/kernel/feature/kernel_umount.c" || {
  echo "::error::SukiSU 40901 kernel_umount native path is missing"
  exit 1
}
grep -qF 'ksu_handle_execveat_sucompat' "$KSU_TREE/kernel/feature/sucompat.c" || {
  echo "::error::SukiSU 40901 sucompat backend is missing"
  exit 1
}
grep -qF 'long __nocfi ksu_hook_execveat' "$KSU_TREE/kernel/hook/syscall_event_bridge.c" || {
  echo "::error::SukiSU 40901 execveat syscall bridge is missing"
  exit 1
}
grep -qF 'ksu_register_syscall_hook(__NR_execveat, ksu_hook_execveat);' \
  "$KSU_TREE/kernel/hook/syscall_hook_manager.c" || {
  echo "::error::SukiSU 40901 execveat hook registration is missing"
  exit 1
}
grep -qF 'ksu_register_syscall_hook(__NR_newfstatat, ksu_hook_newfstatat);' \
  "$KSU_TREE/kernel/hook/syscall_hook_manager.c" || {
  echo "::error::SukiSU 40901 newfstatat hook registration is missing"
  exit 1
}
grep -qF 'ksu_register_syscall_hook(__NR_faccessat, ksu_hook_faccessat);' \
  "$KSU_TREE/kernel/hook/syscall_hook_manager.c" || {
  echo "::error::SukiSU 40901 faccessat hook registration is missing"
  exit 1
}
grep -qF 'ksu_syscall_table_hook(__NR_read, ksu_sys_read, &orig_sys_read);' \
  "$KSU_TREE/kernel/runtime/ksud_integration.c" || {
  echo "::error::SukiSU 40901 read syscall-table hook is missing"
  exit 1
}
grep -qF 'ksu_syscall_table_hook(__NR_fstat, ksu_sys_fstat, &orig_sys_fstat);' \
  "$KSU_TREE/kernel/runtime/ksud_integration.c" || {
  echo "::error::SukiSU 40901 fstat syscall-table hook is missing"
  exit 1
}

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
  'ksu_susfs_dispatch_path_compat' \
  'case CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT:' \
  'case CMD_SUSFS_SET_ANDROID_DATA_ROOT_PATH:' \
  'case CMD_SUSFS_SET_SDCARD_ROOT_PATH:'; do
  grep -RqF "$needle" "$KSU_TREE" || {
    echo "::error::ZeroMount/SUSFS dispatcher compatibility is missing: $needle"
    exit 1
  }
done

# The legacy ZeroMount maps hook overlaps the pinned SUSFS show_map_vma() and
# caused a real apexd Oops on e3q. SUSFS SUS_MAP supplies map hiding, so the
# unsafe duplicate task_mmu hook must remain absent.
if grep -qF 'zeromount_spoof_mmap_metadata' "$COMMON_TREE/fs/proc/task_mmu.c"; then
  echo "::error::Unsafe duplicate ZeroMount task_mmu hook was reintroduced"
  exit 1
fi

echo "Verified SukiSU 40901 native hooks, ZeroMount VFS hooks, full statfs spoofing, SUSFS ${SUSFS_EXPECTED_VERSION:-pinned} bridge, and external-directory compatibility (read-only)"
