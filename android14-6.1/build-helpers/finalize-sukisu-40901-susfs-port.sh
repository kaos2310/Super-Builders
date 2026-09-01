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
    """Remove CONFIG_KSU_SUSFS preprocessor blocks containing generic KSU hooks.

    SUSFS 598370fe changed the execveat guard from
    susfs_is_current_proc_umounted() to susfs_is_current_proc_no_su().  Matching
    the semantic hook tokens instead of one exact patch body keeps this cleanup
    stable across that upstream change while leaving unrelated SUSFS VFS logic
    untouched.
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
# hook manager. Remove only the generic direct callbacks from the GKI patch.
edit("drivers/input/input.c", [
    (r'\n#ifdef CONFIG_KSU_SUSFS\nextern struct static_key_true ksu_is_input_hook_enabled;\nextern __attribute__\(\(cold\)\) int ksu_handle_input_handle_event\(\n\s*unsigned int \*type, unsigned int \*code, int \*value\);\n#endif\n', '\n', 'generic SUSFS input declarations'),
    (r'\n#ifdef CONFIG_KSU_SUSFS\n\s*if \(static_branch_unlikely\(&ksu_is_input_hook_enabled\)\)\n\s*ksu_handle_input_handle_event\(&type, &code, &value\);\n#endif\n', '\n', 'generic SUSFS input callback'),
])

# Do not key this cleanup to the old susfs_is_current_proc_umounted() spelling.
# Current SUSFS 598370fe uses susfs_is_current_proc_no_su(), which is what broke
# run 33549061504 when the declarations were removed but the direct hook stayed.
strip_susfs_blocks_with_tokens("fs/exec.c", (
    "ksu_handle_execveat(",
    "ksu_handle_execveat_sucompat(",
    "ksu_su_compat_enabled",
    "susfs_is_current_proc_no_su(",
    "susfs_is_sdcard_android_data_not_decrypted",
))

edit("kernel/sys.c", [
    (r'\n#ifdef CONFIG_KSU_SUSFS\nextern int ksu_handle_setresuid\(uid_t ruid, uid_t euid, uid_t suid\);\n#endif\n', '\n', 'generic SUSFS setresuid declaration'),
    (r'\n#ifdef CONFIG_KSU_SUSFS\n\s*\(void\)ksu_handle_setresuid\(ruid, euid, suid\);\n#endif\n', '\n', 'generic SUSFS direct setresuid hook'),
])

print("Removed generic KSU direct hooks that conflict with SukiSU Ultra 40901")
PY

# The SukiSU-native SUSFS setuid marker deliberately reuses the same zygote
# predicate as kernel/feature/kernel_umount.c.  Its declaration lives in
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

# Hard gates: the GKI side must now defer execve/execveat/setresuid/input handling
# to SukiSU's native hook stack, while the SUSFS reboot ABI remains wired.
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
! grep -qF 'ksu_handle_setresuid(ruid, euid, suid)' "$COMMON/kernel/sys.c"
! grep -qF 'ksu_is_input_hook_enabled' "$COMMON/drivers/input/input.c"
grep -qF 'ksu_handle_sys_reboot(magic1, magic2, cmd, &arg)' "$COMMON/kernel/reboot.c"

grep -qF '#include "selinux/selinux.h"' "$SETUID_HOOK"
grep -qF 'bool is_zygote(const struct cred *cred);' "$KSU_ROOT/kernel/selinux/selinux.h"
grep -qF 'susfs_set_current_proc_umounted();' "$SETUID_HOOK"

grep -qF 'int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg)' \
  "$KSU_ROOT/kernel/supercall/dispatch.c"
grep -qF 'case CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT:' "$KSU_ROOT/kernel/supercall/dispatch.c"
grep -qF 'ksu_susfs_dispatch_path_compat' "$KSU_ROOT/kernel/supercall/dispatch.c"

# Preserve the requested SukiSU 40901 execution paths.
grep -qF 'new_uid != WEBVIEW_ZYGOTE_UID' "$KSU_ROOT/kernel/feature/kernel_umount.c"
grep -qF 'ksu_handle_execveat_sucompat' "$KSU_ROOT/kernel/feature/sucompat.c"
grep -qF 'long __nocfi ksu_hook_execveat' "$KSU_ROOT/kernel/hook/syscall_event_bridge.c"
grep -qF 'ksu_register_syscall_hook(__NR_execveat, ksu_hook_execveat);' "$KSU_ROOT/kernel/hook/syscall_hook_manager.c"
grep -qF 'bool ksu_uid_should_umount(uid_t uid)' "$KSU_ROOT/kernel/policy/allowlist.c"
grep -qF 'void ksu_handle_execveat_ksud' "$KSU_ROOT/kernel/runtime/ksud_integration.c"

echo "Finalized SukiSU Ultra 40901 + SUSFS 2.2 port without regressing execveat/WebView/umount semantics"
