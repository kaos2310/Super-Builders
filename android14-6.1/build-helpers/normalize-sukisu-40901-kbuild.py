#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

EXPECTED_PIN = "9fbe8fe8ca90c62c259c5894bf96d02ac31209b9"

if len(sys.argv) != 2:
    raise SystemExit("usage: normalize-sukisu-40901-kbuild.py <ksu-root>")

ksu_root = Path(sys.argv[1]).resolve()
kbuild = ksu_root / "kernel/Kbuild"
if not kbuild.is_file():
    raise SystemExit(f"SukiSU Kbuild is missing: {kbuild}")

head = subprocess.check_output(
    ["git", "-C", str(ksu_root), "rev-parse", "HEAD"], text=True
).strip()
if head != EXPECTED_PIN:
    raise SystemExit(f"SukiSU git HEAD mismatch: expected {EXPECTED_PIN}, got {head}")

# Simonpunk's generic SUSFS bridge targets a nearby KernelSU/SukiSU hook
# architecture. Its KernelSU integration patch removes the native 40901 hook,
# symbol-resolver and arch syscall objects from kernel/Kbuild. Our lifecycle,
# setuid and dispatcher reconciliation deliberately keeps SukiSU 40901's native
# architecture, so those implementation objects must remain linked as well.
pinned = subprocess.check_output(
    ["git", "-C", str(ksu_root), "show", f"{EXPECTED_PIN}:kernel/Kbuild"], text=True
)
text = kbuild.read_text(encoding="utf-8")

native_hook_block = (
    "kernelsu-objs += hook/lsm_hook.o\n"
    "kernelsu-objs += hook/setuid_hook.o\n"
    "kernelsu-objs += hook/syscall_event_bridge.o\n"
    "kernelsu-objs += hook/syscall_hook_manager.o\n"
    "kernelsu-objs += hook/tp_marker.o\n"
    "ifeq ($(CONFIG_ARM64),y)\n"
    "kernelsu-objs += hook/arm64/patch_memory.o\n"
    "kernelsu-objs += hook/arm64/syscall_hook.o\n"
    "else ifeq ($(CONFIG_X86_64),y)\n"
    "kernelsu-objs += hook/x86_64/patch_memory.o\n"
    "kernelsu-objs += hook/x86_64/syscall_hook.o\n"
    "endif\n"
)
resolver_line = "kernelsu-objs += infra/symbol_resolver.o\n"

for token in (native_hook_block, resolver_line):
    if token not in pinned:
        raise SystemExit("Pinned SukiSU 40901 Kbuild no longer matches the expected native object contract")

required_sources = (
    "kernel/hook/lsm_hook.c",
    "kernel/hook/setuid_hook.c",
    "kernel/hook/syscall_event_bridge.c",
    "kernel/hook/syscall_hook_manager.c",
    "kernel/hook/tp_marker.c",
    "kernel/hook/arm64/patch_memory.c",
    "kernel/hook/arm64/syscall_hook.c",
    "kernel/infra/symbol_resolver.c",
)
for rel in required_sources:
    if not (ksu_root / rel).is_file():
        raise SystemExit(f"Pinned SukiSU native implementation source is missing: {rel}")

required_hook_lines = tuple(
    line + "\n"
    for line in (
        "kernelsu-objs += hook/lsm_hook.o",
        "kernelsu-objs += hook/setuid_hook.o",
        "kernelsu-objs += hook/syscall_event_bridge.o",
        "kernelsu-objs += hook/syscall_hook_manager.o",
        "kernelsu-objs += hook/tp_marker.o",
        "kernelsu-objs += hook/arm64/patch_memory.o",
        "kernelsu-objs += hook/arm64/syscall_hook.o",
        "kernelsu-objs += hook/x86_64/patch_memory.o",
        "kernelsu-objs += hook/x86_64/syscall_hook.o",
    )
)
present = tuple(line in text for line in required_hook_lines)

if all(present):
    print("SukiSU 40901 native hook object block already intact")
elif present == (False, True, False, False, False, False, False, False, False):
    anchor = "kernelsu-objs += hook/setuid_hook.o\n"
    if text.count(anchor) != 1:
        raise SystemExit("Cannot restore native hook object block: setuid Kbuild anchor is not unique")
    text = text.replace(anchor, native_hook_block, 1)
    print("Restored SukiSU 40901 native hook/syscall object block removed by generic SUSFS patch")
else:
    state = ", ".join(
        f"{line.strip()}={'present' if is_present else 'missing'}"
        for line, is_present in zip(required_hook_lines, present)
    )
    raise SystemExit("Partial SukiSU native Kbuild object drift detected; refusing ambiguous repair: " + state)

if resolver_line not in text:
    anchor = "kernelsu-objs += infra/su_mount_ns.o\n"
    if text.count(anchor) != 1:
        raise SystemExit("Cannot restore symbol_resolver.o: su_mount_ns Kbuild anchor is not unique")
    text = text.replace(anchor, anchor + resolver_line, 1)
    print("Restored SukiSU 40901 symbol_resolver.o linkage removed by generic SUSFS patch")

# Preserve the workflow-frozen release identity. Restoring the whole upstream
# Kbuild here would silently undo these deterministic version assignments.
for token in ("KSU_VERSION := 40901", "KSU_VERSION_FULL := v4.2.0-40901"):
    if token not in text:
        raise SystemExit(f"Frozen SukiSU build identity was lost before Kbuild reconciliation: {token}")

for line in required_hook_lines + (resolver_line,):
    if text.count(line) != 1:
        raise SystemExit(f"SukiSU native object linkage is missing or duplicated after repair: {line.strip()}")

if text.count("obj-$(CONFIG_KSU) += kernelsu.o\n") != 1:
    raise SystemExit("SukiSU aggregate kernelsu.o linkage is missing or duplicated")

kbuild.write_text(text, encoding="utf-8")
print("Verified SukiSU 40901 native Kbuild linkage contract after SUSFS reconciliation")
