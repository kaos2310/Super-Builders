#!/bin/bash
set -euo pipefail

COMMON="${1:?common kernel tree}"
KSU_ROOT="${2:?SukiSU Ultra tree}"

python3 - "$COMMON" <<'PY'
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
    """Remove CONFIG_KSU_SUSFS blocks that belong to generic KernelSU hooks.

    The filesystem-side SUSFS patch still carries direct KernelSU callback
    glue. SukiSU Ultra 40901 owns those syscalls through its native hook stack,
    so only exact CONFIG_KSU_SUSFS blocks containing the generic KSU tokens are
    removed. Feature-specific SUSFS blocks such as CONFIG_KSU_SUSFS_SUS_KSTAT,
    CONFIG_KSU_SUSFS_SUS_MOUNT and CONFIG_KSU_SUSFS_OPEN_REDIRECT are preserved.
    """
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

# The generic SUSFS KernelSU patch converts modern KSU hooks into direct kernel
# callbacks. SukiSU Ultra 40901 already owns these paths through its syscall
# hook manager / native init-rc syscall-table hooks. Remove only that generic
# callback glue from the GKI tree; retain the actual SUSFS VFS functionality.
edit("drivers/input/input.c", [
    (r'\n#ifdef CONFIG_KSU_SUSFS\nextern struct static_key_true ksu_is_input_hook_enabled;\nextern __attribute__\(\(cold\)\) int ksu_handle_input_handle_event\(\n\s*unsigned int \*type, unsigned int \*code, int \*value\);\n#endif\n', '\n', 'generic SUSFS input declarations'),
    (r'\n#ifdef CONFIG_KSU_SUSFS\n\s*if \(static_branch_unlikely\(&ksu_is_input_hook_enabled\)\)\n\s*ksu_handle_input_handle_event\(&type, &code, &value\);\n#endif\n', '\n', 'generic SUSFS input callback'),
])

# Do not key this cleanup to one SUSFS process-state helper spelling. Upstream
# changed susfs_is_current_proc_umounted() to susfs_is_current_proc_no_su(); the
# KSU hook tokens are the stable semantic discriminator.
strip_susfs_blocks_with_tokens("fs/exec.c", (
    "ksu_handle_execveat(",
    "ksu_handle_execveat_sucompat(",
    "ksu_su_compat_enabled",
    "susfs_is_current_proc_no_su(",
    "susfs_is_sdcard_android_data_not_decrypted",
))

# faccessat is already registered by SukiSU 40901's syscall_hook_manager.
strip_susfs_blocks_with_tokens("fs/open.c", (
    "ksu_handle_faccessat(",
    "ksu_su_compat_enabled",
    "__ksu_is_allow_uid_for_current(",
))

# SukiSU 40901 installs its own temporary __NR_read/__NR_fstat init-rc hooks.
# The direct calls added to GKI read_write.c/stat.c are KernelSU-specific glue
# and must not reference Suki's private/static implementation symbols.
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
    (r'\n#ifdef CONFIG_KSU_SUSFS\nextern int ksu_handle_setresuid\(uid_t ruid, uid_t euid, uid_t suid\);\n#endif\n', '\n', 'generic SUSFS setresuid declaration'),
    (r'\n#ifdef CONFIG_KSU_SUSFS\n\s*\(void\)ksu_handle_setresuid\(ruid, euid, suid\);\n#endif\n', '\n', 'generic SUSFS direct setresuid hook'),
])

print("Removed generic KSU direct hooks that conflict with SukiSU Ultra 40901")
PY

# The SukiSU-native SUSFS setuid marker deliberately reuses the same zygote
# predicate as kernel/feature/kernel_umount.c. Its declaration lives in
# selinux/selinux.h, so make that dependency explicit in setuid_hook.c.
SETUID_HOOK="$KSU_ROOT/kernel/hook/setuid_hook.c"
[[ -f "$SETUID_HOOK" ]] || { echo "::error::Missing SukiSU setuid hook"; exit 1; }
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

# Hard gates: no KernelSU-generic direct syscall glue may survive on the GKI
# side. If a future SUSFS patch moves/renames one of these hooks, fail before
# spending ~20 minutes compiling and linking vmlinux.
for token in \
  'ksu_handle_execveat(&fd, &filename' \
  'ksu_handle_execveat_sucompat(&fd, &filename' \
  'ksu_su_compat_enabled' \
  'susfs_is_current_proc_no_su()' \
  'susfs_is_sdcard_android_data_not_decrypted'; do
  if grep -qF "$token" "$COMMON/fs/exec.c"; then
    echo "::error::Generic SUSFS exec hook survived SukiSU finalization: $token"
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
  if grep -qF "$token" "$COMMON/$rel"; then
    echo "::error::Generic SUSFS direct hook survived SukiSU finalization: $rel: $token"
    exit 1
  fi
done

! grep -qF 'ksu_handle_setresuid(ruid, euid, suid)' "$COMMON/kernel/sys.c"
! grep -qF 'ksu_is_input_hook_enabled' "$COMMON/drivers/input/input.c"
grep -qF 'ksu_handle_sys_reboot(magic1, magic2, cmd, &arg)' "$COMMON/kernel/reboot.c"

# Assert that the legitimate filesystem-side SUSFS functionality was retained
# while the generic KSU glue above was stripped.
grep -qF 'susfs_sus_kstat_spoof_generic_fillattr' "$COMMON/fs/stat.c"
grep -qF 'susfs_get_non_sus_mnt_id_from_mnt' "$COMMON/fs/stat.c"

grep -qF '#include "selinux/selinux.h"' "$SETUID_HOOK"
grep -qF 'bool is_zygote(const struct cred *cred);' "$KSU_ROOT/kernel/selinux/selinux.h"
grep -qF 'susfs_set_current_proc_umounted();' "$SETUID_HOOK"

grep -qF 'int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg)' \
  "$KSU_ROOT/kernel/supercall/dispatch.c"
grep -qF 'case CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT:' "$KSU_ROOT/kernel/supercall/dispatch.c"
grep -qF 'ksu_susfs_dispatch_path_compat' "$KSU_ROOT/kernel/supercall/dispatch.c"

# Preserve and explicitly prove the requested SukiSU 40901 native execution
# paths that replace the generic GKI callbacks removed above.
grep -qF 'new_uid != WEBVIEW_ZYGOTE_UID' "$KSU_ROOT/kernel/feature/kernel_umount.c"
grep -qF 'ksu_handle_execveat_sucompat' "$KSU_ROOT/kernel/feature/sucompat.c"
grep -qF 'long __nocfi ksu_hook_execveat' "$KSU_ROOT/kernel/hook/syscall_event_bridge.c"
grep -qF 'ksu_register_syscall_hook(__NR_execveat, ksu_hook_execveat);' "$KSU_ROOT/kernel/hook/syscall_hook_manager.c"
grep -qF 'ksu_register_syscall_hook(__NR_newfstatat, ksu_hook_newfstatat);' "$KSU_ROOT/kernel/hook/syscall_hook_manager.c"
grep -qF 'ksu_register_syscall_hook(__NR_faccessat, ksu_hook_faccessat);' "$KSU_ROOT/kernel/hook/syscall_hook_manager.c"
grep -qF 'ksu_syscall_table_hook(__NR_read, ksu_sys_read, &orig_sys_read);' "$KSU_ROOT/kernel/runtime/ksud_integration.c"
grep -qF 'ksu_syscall_table_hook(__NR_fstat, ksu_sys_fstat, &orig_sys_fstat);' "$KSU_ROOT/kernel/runtime/ksud_integration.c"
grep -qF 'bool ksu_uid_should_umount(uid_t uid)' "$KSU_ROOT/kernel/policy/allowlist.c"
grep -qF 'void ksu_handle_execveat_ksud' "$KSU_ROOT/kernel/runtime/ksud_integration.c"

echo "Finalized SukiSU Ultra 40901 + SUSFS 2.2 without generic KernelSU syscall glue regressions"
