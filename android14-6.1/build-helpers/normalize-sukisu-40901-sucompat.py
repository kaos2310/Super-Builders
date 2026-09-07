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

# Simonpunk's generic SUSFS patch switches sucompat to the direct common-kernel
# hook ABI (static-key enable state plus ksu_handle_faccessat/stat style entry
# points). This build deliberately removes those direct common hooks and keeps
# SukiSU 40901's syscall_event_bridge/syscall_hook_manager architecture. Restore
# the matching native sucompat implementation and header from the immutable pin.
files = (
    "kernel/feature/sucompat.c",
    "kernel/feature/sucompat.h",
)
restored: dict[str, str] = {}
for rel in files:
    target = ksu_root / rel
    if not target.is_file():
        raise SystemExit(f"SukiSU sucompat source is missing: {target}")
    data = subprocess.check_output(
        ["git", "-C", str(ksu_root), "show", f"{EXPECTED_PIN}:{rel}"], text=True
    )
    restored[rel] = data

c_text = restored["kernel/feature/sucompat.c"]
h_text = restored["kernel/feature/sucompat.h"]

required_c = (
    "bool ksu_su_compat_enabled __read_mostly = true;",
    "long ksu_handle_faccessat_sucompat(int orig_nr, struct pt_regs *regs)",
    "long ksu_handle_stat_sucompat(int orig_nr, struct pt_regs *regs)",
    "long ksu_handle_execve_sucompat(const char __user **filename_user, int orig_nr, struct pt_regs *regs)",
    "long ksu_handle_execveat_sucompat(const char __user **filename_user, int orig_nr, struct pt_regs *regs)",
    "return ksu_syscall_table[orig_nr](regs);",
)
required_h = (
    "extern bool ksu_su_compat_enabled;",
    "long ksu_handle_faccessat_sucompat(int orig_nr, struct pt_regs *regs);",
    "long ksu_handle_stat_sucompat(int orig_nr, struct pt_regs *regs);",
    "long ksu_handle_execve_sucompat(const char __user **filename_user, int orig_nr, struct pt_regs *regs);",
    "long ksu_handle_execveat_sucompat(const char __user **filename_user, int orig_nr, struct pt_regs *regs);",
)
for token in required_c:
    if token not in c_text:
        raise SystemExit(f"Pinned SukiSU 40901 sucompat.c lost native ABI token: {token}")
for token in required_h:
    if token not in h_text:
        raise SystemExit(f"Pinned SukiSU 40901 sucompat.h lost native ABI token: {token}")

for forbidden in (
    "DEFINE_STATIC_KEY_TRUE(ksu_su_compat_enabled)",
    "int ksu_handle_faccessat(int *dfd",
    "int ksu_handle_stat(int *dfd",
):
    if forbidden in c_text or forbidden in h_text:
        raise SystemExit(f"Direct-hook SUSFS sucompat ABI unexpectedly exists in pinned SukiSU: {forbidden}")

for rel, data in restored.items():
    (ksu_root / rel).write_text(data, encoding="utf-8")

# Validate the native caller contract that will be linked again by the Kbuild
# normalizer. This catches a future SukiSU rebase before the expensive build.
bridge = ksu_root / "kernel/hook/syscall_event_bridge.c"
if not bridge.is_file():
    raise SystemExit(f"Native SukiSU syscall event bridge is missing: {bridge}")
bridge_text = bridge.read_text(encoding="utf-8")
for token in (
    "ksu_handle_stat_sucompat(orig_nr",
    "ksu_handle_faccessat_sucompat(orig_nr",
    "ksu_handle_execve_sucompat(filename_user",
    "ksu_handle_execveat_sucompat(filename_user",
):
    if token not in bridge_text:
        raise SystemExit(f"Native SukiSU syscall bridge lost expected sucompat call: {token}")

print("Restored and verified SukiSU 40901 native sucompat ABI after generic SUSFS patch")
