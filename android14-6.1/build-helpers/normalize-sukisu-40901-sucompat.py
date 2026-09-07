#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

EXPECTED_PIN = "9fbe8fe8ca90c62c259c5894bf96d02ac31209b9"

if len(sys.argv) != 2:
    raise SystemExit("usage: normalize-sukisu-40901-sucompat.py <ksu-root>")

ksu_root = Path(sys.argv[1]).resolve()
if not ksu_root.is_dir():
    raise SystemExit(f"SukiSU tree is missing: {ksu_root}")

head = subprocess.check_output(
    ["git", "-C", str(ksu_root), "rev-parse", "HEAD"], text=True
).strip()
if head != EXPECTED_PIN:
    raise SystemExit(f"SukiSU git HEAD mismatch: expected {EXPECTED_PIN}, got {head}")

# Simonpunk's generic SUSFS patch switches sucompat/SULOG to the direct
# common-kernel hook ABI (static-key enable state plus struct user_arg_ptr
# entry points). This build deliberately removes those direct common hooks and
# keeps SukiSU 40901's syscall_event_bridge/syscall_hook_manager architecture.
# Restore the complete matching native sucompat + SULOG contract from the
# immutable SukiSU pin. Restoring event.c together with event.h is intentional:
# the pinned implementation owns its compat/native user_arg_ptr conversion
# privately, while the generic SUSFS patch expects a caller-owned user_arg_ptr.
files = (
    "kernel/feature/sucompat.c",
    "kernel/feature/sucompat.h",
    "kernel/sulog/event.c",
    "kernel/sulog/event.h",
)
restored: dict[str, str] = {}
for rel in files:
    target = ksu_root / rel
    if not target.is_file():
        raise SystemExit(f"SukiSU native ABI source is missing: {target}")
    data = subprocess.check_output(
        ["git", "-C", str(ksu_root), "show", f"{EXPECTED_PIN}:{rel}"], text=True
    )
    restored[rel] = data

c_text = restored["kernel/feature/sucompat.c"]
h_text = restored["kernel/feature/sucompat.h"]
event_c_text = restored["kernel/sulog/event.c"]
event_h_text = restored["kernel/sulog/event.h"]

required_c = (
    "bool ksu_su_compat_enabled __read_mostly = true;",
    "long ksu_handle_faccessat_sucompat(int orig_nr, struct pt_regs *regs)",
    "long ksu_handle_stat_sucompat(int orig_nr, struct pt_regs *regs)",
    "long ksu_handle_execve_sucompat(const char __user **filename_user, int orig_nr, struct pt_regs *regs)",
    "long ksu_handle_execveat_sucompat(const char __user **filename_user, int orig_nr, struct pt_regs *regs)",
    "pending_sucompat = ksu_sulog_capture_sucompat(*filename_user, argv_user, GFP_KERNEL);",
    "return ksu_syscall_table[orig_nr](regs);",
)
required_h = (
    "extern bool ksu_su_compat_enabled;",
    "long ksu_handle_faccessat_sucompat(int orig_nr, struct pt_regs *regs);",
    "long ksu_handle_stat_sucompat(int orig_nr, struct pt_regs *regs);",
    "long ksu_handle_execve_sucompat(const char __user **filename_user, int orig_nr, struct pt_regs *regs);",
    "long ksu_handle_execveat_sucompat(const char __user **filename_user, int orig_nr, struct pt_regs *regs);",
)
required_event_h = (
    "ksu_sulog_capture_root_execve(const char __user *filename_user,",
    "ksu_sulog_capture_sucompat(const char __user *filename_user,",
    "const char __user *const __user *argv_user, gfp_t gfp);",
)
# Keep these as an explicit list: each token represents a separate ABI property.
required_event_c = [
    "struct user_arg_ptr {",
    "static struct user_arg_ptr ksu_sulog_user_argv(const char __user *const __user *argv_user)",
    "static const char __user *ksu_sulog_get_user_arg_ptr(struct user_arg_ptr argv, int nr)",
    "static __u32 ksu_sulog_flatten_argv(const char __user *const __user *argv_user, char *dst, __u32 dst_len)",
    "const char __user *const __user *argv_user, gfp_t gfp)",
    "ksu_sulog_capture_root_execve(const char __user *filename_user,",
    "ksu_sulog_capture_sucompat(const char __user *filename_user,",
]
for token in required_c:
    if token not in c_text:
        raise SystemExit(f"Pinned SukiSU 40901 sucompat.c lost native ABI token: {token}")
for token in required_h:
    if token not in h_text:
        raise SystemExit(f"Pinned SukiSU 40901 sucompat.h lost native ABI token: {token}")
for token in required_event_h:
    if token not in event_h_text:
        raise SystemExit(f"Pinned SukiSU 40901 SULOG header lost native ABI token: {token}")
for token in required_event_c:
    if token not in event_c_text:
        raise SystemExit(f"Pinned SukiSU 40901 SULOG implementation lost native ABI token: {token}")

for forbidden in (
    "DEFINE_STATIC_KEY_TRUE(ksu_su_compat_enabled)",
    "int ksu_handle_faccessat(int *dfd",
    "int ksu_handle_stat(int *dfd",
):
    if forbidden in c_text or forbidden in h_text:
        raise SystemExit(f"Direct-hook SUSFS sucompat ABI unexpectedly exists in pinned SukiSU: {forbidden}")

for forbidden in (
    '#include "runtime/ksud.h"',
    "ksu_sulog_capture_sucompat(const char *filename,",
    "struct user_arg_ptr *argv_user",
):
    if forbidden in event_h_text:
        raise SystemExit(f"Direct-hook SUSFS SULOG ABI unexpectedly exists in pinned SukiSU header: {forbidden}")

for rel, data in restored.items():
    (ksu_root / rel).write_text(data, encoding="utf-8")

# Validate both native callers that will be linked again by the Kbuild
# normalizer. This catches a future SukiSU rebase before the expensive build
# and prevents the sucompat and root-exec SULOG signatures drifting apart.
bridge = ksu_root / "kernel/hook/syscall_event_bridge.c"
if not bridge.is_file():
    raise SystemExit(f"Native SukiSU syscall event bridge is missing: {bridge}")
bridge_text = bridge.read_text(encoding="utf-8")
for token in (
    "ksu_handle_stat_sucompat(orig_nr",
    "ksu_handle_faccessat_sucompat(orig_nr",
    "ksu_handle_execve_sucompat(filename_user",
    "ksu_handle_execveat_sucompat(filename_user",
    "pending_root_execve = ksu_sulog_capture_root_execve(*filename_user, argv_user, GFP_KERNEL);",
):
    if token not in bridge_text:
        raise SystemExit(f"Native SukiSU syscall bridge lost expected call: {token}")

# Verify the files written to disk expose one coherent public SULOG contract.
written_event_h = (ksu_root / "kernel/sulog/event.h").read_text(encoding="utf-8")
written_event_c = (ksu_root / "kernel/sulog/event.c").read_text(encoding="utf-8")
if written_event_h.count("ksu_sulog_capture_root_execve(") != 1:
    raise SystemExit("SukiSU root-exec SULOG declaration is missing or duplicated after normalization")
if written_event_h.count("ksu_sulog_capture_sucompat(") != 1:
    raise SystemExit("SukiSU sucompat SULOG declaration is missing or duplicated after normalization")
if written_event_c.count("ksu_sulog_capture_root_execve(") != 1:
    raise SystemExit("SukiSU root-exec SULOG definition is missing or duplicated after normalization")
if written_event_c.count("ksu_sulog_capture_sucompat(") != 1:
    raise SystemExit("SukiSU sucompat SULOG definition is missing or duplicated after normalization")

print(
    "Restored and verified SukiSU 40901 native sucompat + SULOG ABI after generic SUSFS patch "
    "(sucompat and root-exec callers reconciled)"
)
