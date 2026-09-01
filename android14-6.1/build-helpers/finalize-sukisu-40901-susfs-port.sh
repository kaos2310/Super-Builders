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

# The generic SUSFS KernelSU patch converts modern KSU hooks into direct kernel
# callbacks. SukiSU Ultra 40901 already owns these paths through its syscall
# hook manager. Remove only the generic direct callbacks from the GKI patch.
edit("drivers/input/input.c", [
    (r'\n#ifdef CONFIG_KSU_SUSFS\nextern struct static_key_true ksu_is_input_hook_enabled;\nextern __attribute__\(\(cold\)\) int ksu_handle_input_handle_event\(\n\s*unsigned int \*type, unsigned int \*code, int \*value\);\n#endif\n', '\n', 'generic SUSFS input declarations'),
    (r'\n#ifdef CONFIG_KSU_SUSFS\n\s*if \(static_branch_unlikely\(&ksu_is_input_hook_enabled\)\)\n\s*ksu_handle_input_handle_event\(&type, &code, &value\);\n#endif\n', '\n', 'generic SUSFS input callback'),
])

edit("fs/exec.c", [
    (r'\n#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs_def.h>\n#endif\n', '\n', 'generic SUSFS exec include'),
    (r'\n#ifdef CONFIG_KSU_SUSFS\nextern struct static_key_true ksu_su_compat_enabled;\nextern struct static_key_true susfs_is_sdcard_android_data_not_decrypted;\nextern bool __ksu_is_allow_uid_for_current\(uid_t uid\);\nextern int ksu_handle_execveat\(int \*fd, struct filename \*\*filename_ptr, void \*argv,\n\s*void \*envp, int \*flags\);\nextern int ksu_handle_execveat_sucompat\(int \*fd, struct filename \*\*filename_ptr, void \*argv,\n\s*void \*envp, int \*flags\);\n#endif\n', '\n', 'generic SUSFS exec declarations'),
    (r'\n#ifdef CONFIG_KSU_SUSFS\n\s*if \(likely\(susfs_is_current_proc_(?:no_su|umounted)\(\)\)\)\n\s*goto orig_flow;\n\n\s*if \(static_branch_likely\(&ksu_su_compat_enabled\)\) \{\n\s*if \(static_branch_unlikely\(&susfs_is_sdcard_android_data_not_decrypted\)\)\n\s*ksu_handle_execveat\(&fd, &filename, &argv, &envp, &flags\);\n\s*else\n\s*ksu_handle_execveat_sucompat\(&fd, &filename, &argv, &envp, &flags\);\n\s*\}\n\norig_flow:\n#endif\n', '\n', 'generic SUSFS direct exec hook'),
])

edit("kernel/sys.c", [
    (r'\n#ifdef CONFIG_KSU_SUSFS\nextern int ksu_handle_setresuid\(uid_t ruid, uid_t euid, uid_t suid\);\n#endif\n', '\n', 'generic SUSFS setresuid declaration'),
    (r'\n#ifdef CONFIG_KSU_SUSFS\n\s*\(void\)ksu_handle_setresuid\(ruid, euid, suid\);\n#endif\n', '\n', 'generic SUSFS direct setresuid hook'),
])

print("Removed generic KSU direct hooks that conflict with SukiSU Ultra 40901")
PY

# Hard gates: the GKI side must now defer execve/execveat/setresuid/input handling
# to SukiSU's native hook stack, while the SUSFS reboot ABI remains wired.
reject_direct_hook() {
  local path="$1"
  local needle="$2"
  local label="$3"
  if grep -qF "$needle" "$path"; then
    echo "::error::Generic SUSFS direct $label hook remains in $path"
    exit 1
  fi
}

reject_direct_hook "$COMMON/fs/exec.c" 'ksu_handle_execveat(&fd, &filename' 'execveat'
reject_direct_hook "$COMMON/kernel/sys.c" 'ksu_handle_setresuid(ruid, euid, suid)' 'setresuid'
reject_direct_hook "$COMMON/drivers/input/input.c" 'ksu_is_input_hook_enabled' 'input'
grep -qF 'ksu_handle_sys_reboot(magic1, magic2, cmd, &arg)' "$COMMON/kernel/reboot.c"

grep -qF 'int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg)' \
  "$KSU_ROOT/kernel/supercall/dispatch.c"
grep -qF 'case CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT:' "$KSU_ROOT/kernel/supercall/dispatch.c"
grep -qF 'ksu_susfs_dispatch_path_compat' "$KSU_ROOT/kernel/supercall/dispatch.c"
grep -qF '#include "selinux/selinux.h"' "$KSU_ROOT/kernel/hook/setuid_hook.c"

# Preserve the requested SukiSU 40901 execution paths.
grep -qF 'new_uid != WEBVIEW_ZYGOTE_UID' "$KSU_ROOT/kernel/feature/kernel_umount.c"
grep -qF 'ksu_handle_execveat_sucompat' "$KSU_ROOT/kernel/feature/sucompat.c"
grep -qF 'long __nocfi ksu_hook_execveat' "$KSU_ROOT/kernel/hook/syscall_event_bridge.c"
grep -qF 'ksu_register_syscall_hook(__NR_execveat, ksu_hook_execveat);' "$KSU_ROOT/kernel/hook/syscall_hook_manager.c"
grep -qF 'bool ksu_uid_should_umount(uid_t uid)' "$KSU_ROOT/kernel/policy/allowlist.c"
grep -qF 'void ksu_handle_execveat_ksud' "$KSU_ROOT/kernel/runtime/ksud_integration.c"

echo "Finalized SukiSU Ultra 40901 + SUSFS 2.2 port without regressing execveat/WebView/umount semantics"
