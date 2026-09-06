#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common kernel tree}"
KSU_TREE="${2:?KernelSU tree}"

# Simonpunk's generic KernelSU bridge carries direct syscall/VFS callback glue
# for a nearby KernelSU/SukiSU layout. SukiSU Ultra 40901 already owns these
# syscall paths through its native hook manager / init-rc syscall-table hooks.
# Remove only the generic CONFIG_KSU_SUSFS callback blocks after ZeroMount has
# been applied, while preserving SUSFS feature-specific VFS blocks.
python3 - "$COMMON_TREE" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])


def edit(rel, transforms):
    p = root / rel
    if not p.is_file():
        raise SystemExit(f"Missing common source: {rel}")
    text = p.read_text(encoding="utf-8")
    for pattern, repl, label in transforms:
        new, count = re.subn(pattern, repl, text, flags=re.MULTILINE)
        if count > 1:
            raise SystemExit(f"Unexpected duplicate {label} in {rel}: {count}")
        text = new
    p.write_text(text, encoding="utf-8")


def strip_susfs_blocks_with_tokens(rel, tokens):
    p = root / rel
    if not p.is_file():
        raise SystemExit(f"Missing common source: {rel}")
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    out = []
    removed = 0
    i = 0
    while i < len(lines):
        if lines[i].strip() != "#ifdef CONFIG_KSU_SUSFS":
            out.append(lines[i])
            i += 1
            continue

        depth = 1
        j = i + 1
        while j < len(lines) and depth:
            directive = lines[j].strip()
            if directive.startswith(("#if ", "#ifdef ", "#ifndef ")):
                depth += 1
            elif directive == "#endif" or directive.startswith("#endif "):
                depth -= 1
            j += 1
        if depth:
            raise SystemExit(f"Unterminated CONFIG_KSU_SUSFS block in {rel}")

        block = "".join(lines[i:j])
        if any(token in block for token in tokens):
            removed += 1
        else:
            out.extend(lines[i:j])
        i = j

    p.write_text("".join(out), encoding="utf-8")
    print(f"Removed {removed} generic SUSFS direct-hook block(s) from {rel}")


edit("drivers/input/input.c", [
    (
        r'\n#ifdef CONFIG_KSU_SUSFS\nextern struct static_key_true ksu_is_input_hook_enabled;\nextern __attribute__\(\(cold\)\) int ksu_handle_input_handle_event\(\n\s*unsigned int \*type, unsigned int \*code, int \*value\);\n#endif\n',
        '\n',
        'generic SUSFS input declarations',
    ),
    (
        r'\n#ifdef CONFIG_KSU_SUSFS\n\s*if \(static_branch_unlikely\(&ksu_is_input_hook_enabled\)\)\n\s*ksu_handle_input_handle_event\(&type, &code, &value\);\n#endif\n',
        '\n',
        'generic SUSFS input callback',
    ),
])

strip_susfs_blocks_with_tokens("fs/exec.c", (
    "ksu_handle_execveat(",
    "ksu_handle_execveat_sucompat(",
    "ksu_su_compat_enabled",
    "susfs_is_current_proc_no_su(",
    "susfs_is_sdcard_android_data_not_decrypted",
))

strip_susfs_blocks_with_tokens("fs/open.c", (
    "ksu_handle_faccessat(",
    "ksu_su_compat_enabled",
    "__ksu_is_allow_uid_for_current(",
))

strip_susfs_blocks_with_tokens("fs/read_write.c", (
    "ksu_is_init_rc_hook_enabled",
    "ksu_handle_sys_read(",
))

strip_susfs_blocks_with_tokens("fs/stat.c", (
    "ksu_is_init_rc_hook_enabled",
    "ksu_handle_vfs_fstat(",
    "ksu_su_compat_enabled",
    "ksu_handle_stat(",
    "__ksu_is_allow_uid_for_current(",
))

edit("kernel/sys.c", [
    (
        r'\n#ifdef CONFIG_KSU_SUSFS\nextern int ksu_handle_setresuid\(uid_t ruid, uid_t euid, uid_t suid\);\n#endif\n',
        '\n',
        'generic SUSFS setresuid declaration',
    ),
    (
        r'\n#ifdef CONFIG_KSU_SUSFS\n\s*\(void\)ksu_handle_setresuid\(ruid, euid, suid\);\n#endif\n',
        '\n',
        'generic SUSFS direct setresuid hook',
    ),
])

print("Removed generic KernelSU direct hooks that conflict with SukiSU Ultra 40901")
PY

# If the SUSFS setuid marker is present, make its SukiSU-native is_zygote()
# dependency explicit. This is idempotent and only touches the KSU file when
# the marker actually exists.
SETUID_HOOK="$KSU_TREE/kernel/hook/setuid_hook.c"
if [[ -f "$SETUID_HOOK" ]] && grep -qF 'susfs_set_current_proc_umounted();' "$SETUID_HOOK"; then
  if ! grep -qF '#include "selinux/selinux.h"' "$SETUID_HOOK"; then
    python3 - "$SETUID_HOOK" <<'PY'
from pathlib import Path
import sys

p = Path(sys.argv[1])
text = p.read_text(encoding="utf-8")
anchor = '#include "feature/kernel_umount.h"\n'
insert = anchor + '#include "selinux/selinux.h"\n'
if text.count(anchor) != 1:
    raise SystemExit(f"Cannot locate unique kernel_umount include in {p}: {text.count(anchor)}")
p.write_text(text.replace(anchor, insert, 1), encoding="utf-8")
PY
  fi
fi

# Fail before compilation if any generic KernelSU callback glue survived.
for token in \
  'ksu_handle_execveat(&fd, &filename' \
  'ksu_handle_execveat_sucompat(&fd, &filename' \
  'ksu_su_compat_enabled' \
  'susfs_is_current_proc_no_su()' \
  'susfs_is_sdcard_android_data_not_decrypted'; do
  if grep -qF "$token" "$COMMON_TREE/fs/exec.c"; then
    echo "::error::Generic SUSFS exec hook survived SukiSU 40901 cleanup: $token"
    exit 1
  fi
done

for spec in \
  'fs/open.c|ksu_handle_faccessat' \
  'fs/read_write.c|ksu_is_init_rc_hook_enabled' \
  'fs/read_write.c|ksu_handle_sys_read' \
  'fs/stat.c|ksu_is_init_rc_hook_enabled' \
  'fs/stat.c|ksu_handle_vfs_fstat' \
  'fs/stat.c|ksu_handle_stat'; do
  rel=${spec%%|*}
  token=${spec#*|}
  if grep -qF "$token" "$COMMON_TREE/$rel"; then
    echo "::error::Generic SUSFS direct hook survived SukiSU 40901 cleanup: $rel: $token"
    exit 1
  fi
done

if grep -qF 'ksu_handle_setresuid(ruid, euid, suid)' "$COMMON_TREE/kernel/sys.c"; then
  echo "::error::Generic SUSFS setresuid hook survived SukiSU 40901 cleanup"
  exit 1
fi
if grep -qF 'ksu_is_input_hook_enabled' "$COMMON_TREE/drivers/input/input.c"; then
  echo "::error::Generic SUSFS input hook survived SukiSU 40901 cleanup"
  exit 1
fi

# Prove the native SukiSU 40901 execution paths that replace the removed glue.
grep -qF 'new_uid != WEBVIEW_ZYGOTE_UID' "$KSU_TREE/kernel/feature/kernel_umount.c"
grep -qF 'ksu_handle_execveat_sucompat' "$KSU_TREE/kernel/feature/sucompat.c"
grep -qF 'long __nocfi ksu_hook_execveat' "$KSU_TREE/kernel/hook/syscall_event_bridge.c"
grep -qF 'ksu_register_syscall_hook(__NR_execveat, ksu_hook_execveat);' \
  "$KSU_TREE/kernel/hook/syscall_hook_manager.c"
grep -qF 'ksu_register_syscall_hook(__NR_newfstatat, ksu_hook_newfstatat);' \
  "$KSU_TREE/kernel/hook/syscall_hook_manager.c"
grep -qF 'ksu_register_syscall_hook(__NR_faccessat, ksu_hook_faccessat);' \
  "$KSU_TREE/kernel/hook/syscall_hook_manager.c"
grep -qF 'ksu_syscall_table_hook(__NR_read, ksu_sys_read, &orig_sys_read);' \
  "$KSU_TREE/kernel/runtime/ksud_integration.c"
grep -qF 'ksu_syscall_table_hook(__NR_fstat, ksu_sys_fstat, &orig_sys_fstat);' \
  "$KSU_TREE/kernel/runtime/ksud_integration.c"

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

[[ -d "$KSU_TREE" ]] || {
  echo "::error::KernelSU tree not found: $KSU_TREE"
  exit 1
}
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

echo "Verified SukiSU 40901 native hooks, ZeroMount VFS hooks, full statfs spoofing, SUSFS ${SUSFS_EXPECTED_VERSION:-pinned} bridge, and external-directory compatibility"
