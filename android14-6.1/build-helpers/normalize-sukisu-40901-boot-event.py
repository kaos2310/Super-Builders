#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

EXPECTED_PIN = "9fbe8fe8ca90c62c259c5894bf96d02ac31209b9"
REL = "kernel/runtime/boot_event.c"

if len(sys.argv) != 2:
    raise SystemExit("usage: normalize-sukisu-40901-boot-event.py <ksu-root>")

ksu_root = Path(sys.argv[1]).resolve()
if not ksu_root.is_dir():
    raise SystemExit(f"SukiSU tree is missing: {ksu_root}")

head = subprocess.check_output(
    ["git", "-C", str(ksu_root), "rev-parse", "HEAD"], text=True
).strip()
if head != EXPECTED_PIN:
    raise SystemExit(f"SukiSU git HEAD mismatch: expected {EXPECTED_PIN}, got {head}")

target = ksu_root / REL
if not target.is_file():
    raise SystemExit(f"SukiSU boot-event source is missing: {target}")

pinned = subprocess.check_output(
    ["git", "-C", str(ksu_root), "show", f"{EXPECTED_PIN}:{REL}"], text=True
)

required = (
    '#include "runtime/ksud.h"',
    "void on_post_fs_data(void)",
    "ksu_load_allow_list();",
    "ksu_observer_init();",
    "ksu_stop_input_hook_runtime();",
    "ksu_selinux_hide_handle_post_fs_data();",
)
for token in required:
    if token not in pinned:
        raise SystemExit(f"Pinned SukiSU 40901 boot_event.c lost native token: {token}")

for forbidden in (
    "ksu_is_input_hook_enabled",
    "static_branch_disable(&ksu_is_input_hook_enabled)",
):
    if forbidden in pinned:
        raise SystemExit(f"Direct-hook SUSFS boot-event ABI unexpectedly exists in pinned SukiSU: {forbidden}")

target.write_text(pinned, encoding="utf-8")
written = target.read_text(encoding="utf-8")

if written.count("ksu_stop_input_hook_runtime();") != 1:
    raise SystemExit("SukiSU native input-hook shutdown call is missing or duplicated after normalization")
if "ksu_is_input_hook_enabled" in written:
    raise SystemExit("Direct-hook SUSFS input static key survived boot-event normalization")

ksud_h = (ksu_root / "kernel/runtime/ksud.h").read_text(encoding="utf-8")
ksud_integration = (ksu_root / "kernel/runtime/ksud_integration.c").read_text(encoding="utf-8")
if "void ksu_stop_input_hook_runtime(void);" not in ksud_h:
    raise SystemExit("SukiSU ksud.h no longer declares ksu_stop_input_hook_runtime()")
if "void ksu_stop_input_hook_runtime(void)" not in ksud_integration:
    raise SystemExit("SukiSU ksud_integration.c no longer defines ksu_stop_input_hook_runtime()")

print(
    "Restored and verified SukiSU 40901 boot-event/input-hook ABI after generic SUSFS patch "
    "(boot_event.c reconciled with native ksud runtime)"
)
