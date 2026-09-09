#!/bin/bash
set -euo pipefail

KSU_TREE="${1:?KernelSU tree}"
TARGET="$KSU_TREE/kernel/supercall/dispatch.c"

[[ -f "$TARGET" ]] || {
  echo "::error::ReSukiSU dispatch source is unavailable: $TARGET"
  exit 1
}

python3 - "$TARGET" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

marker = 'cmd_manage_try_umount: %s is already here!'
if text.count(marker) != 1:
    raise SystemExit(f"Expected exactly one duplicate-umount marker, found {text.count(marker)}")

# Isolate only the duplicate-entry branch. The previous implementation searched
# from the marker to any later `return 0;`, which could cross the closing brace
# and falsely classify an untouched `return -EEXIST;` as already patched.
start = text.index(marker)
branch_end = text.find('}', start)
if branch_end < 0:
    raise SystemExit("Could not isolate duplicate umount ADD branch")

block = text[start:branch_end]
neg = list(re.finditer(r'return\s+-EEXIST\s*;', block))
pos = list(re.finditer(r'return\s+0\s*;', block))

if len(neg) == 1 and not pos:
    match = neg[0]
    block = block[:match.start()] + 'return 0;' + block[match.end():]
    text = text[:start] + block + text[branch_end:]
    print("ReSukiSU duplicate umount ADD patched: -EEXIST -> 0")
elif not neg and len(pos) == 1:
    print("ReSukiSU duplicate umount ADD is already idempotent")
else:
    raise SystemExit(
        "Unexpected duplicate umount ADD return layout: "
        f"-EEXIST={len(neg)} return0={len(pos)}"
    )

# Re-isolate and audit the exact branch after modification. Do not accept a
# return from any later branch in cmd_manage_try_umount().
start = text.index(marker)
branch_end = text.find('}', start)
block = text[start:branch_end]
if re.search(r'return\s+-EEXIST\s*;', block):
    raise SystemExit("Duplicate umount ADD still returns -EEXIST")
if len(re.findall(r'return\s+0\s*;', block)) != 1:
    raise SystemExit("Duplicate umount ADD does not contain exactly one success return")

# Android 17 ReSukiSU compatibility: the Manager app legitimately queries the
# dynamic-manager configuration through the shared IOCTL while still running as
# its app UID.  The old dispatch-level `only_root` check rejects even GET and
# produces noisy -EPERM warnings.  Permit a recognized manager to enter the
# handler, then keep all state-changing operations root-only inside the handler.
handler_marker = '.name = "SET_DYNAMIC_MANAGER",'
if text.count(handler_marker) != 1:
    raise SystemExit(f"Expected exactly one dynamic-manager handler, found {text.count(handler_marker)}")

old_perm = '''        .name = "SET_DYNAMIC_MANAGER",\n        .handler = do_dynamic_manager,\n        .perm_check = only_root '''
new_perm = '''        .name = "SET_DYNAMIC_MANAGER",\n        .handler = do_dynamic_manager,\n        .perm_check = manager_or_root '''
if old_perm in text:
    text = text.replace(old_perm, new_perm, 1)
elif new_perm not in text:
    raise SystemExit("Unexpected dynamic-manager permission layout")

fn_start = text.find('static int do_dynamic_manager(void __user *arg)')
if fn_start < 0:
    raise SystemExit("Could not locate do_dynamic_manager")
fn_end = text.find('\n}\n', fn_start)
if fn_end < 0:
    raise SystemExit("Could not isolate do_dynamic_manager")
fn_end += 3
fn = text[fn_start:fn_end]

write_guard = '''    if (cmd.operation != DYNAMIC_MANAGER_OP_GET && !only_root()) {\n        pr_warn("dynamic manager: non-root write operation denied for uid=%d\\n",\n                ksu_get_uid_t(current_uid()));\n        return -EPERM;\n    }\n\n'''
if write_guard not in fn:
    copy_block = re.search(
        r'(    if \(copy_from_user\(&cmd, arg, sizeof\(cmd\)\)\) \{\n'
        r'        return -EFAULT;\n'
        r'    \}\n\n)', fn
    )
    if not copy_block:
        raise SystemExit("Could not locate dynamic-manager copy_from_user block")
    insert_at = copy_block.end()
    fn = fn[:insert_at] + write_guard + fn[insert_at:]
    text = text[:fn_start] + fn + text[fn_end:]

# Final safety audit: GET can pass manager_or_root, every mutation remains
# protected by only_root inside the handler.
if new_perm not in text:
    raise SystemExit("Dynamic-manager manager_or_root dispatch patch missing")
fn_start = text.find('static int do_dynamic_manager(void __user *arg)')
fn_end = text.find('\n}\n', fn_start) + 3
fn = text[fn_start:fn_end]
if 'cmd.operation != DYNAMIC_MANAGER_OP_GET && !only_root()' not in fn:
    raise SystemExit("Dynamic-manager root-only mutation guard missing")

path.write_text(text, encoding="utf-8")
print("ReSukiSU duplicate kernel umount ADD now returns success")
print("Existing mount-list entry and flags remain unchanged; only duplicate status becomes idempotent")
print("ReSukiSU dynamic-manager GET now permits the recognized Manager app")
print("Dynamic-manager SET/SET_SYNCHRONOUS/WIPE remain root-only")
PY
