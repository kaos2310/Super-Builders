#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

EXPECTED_PIN = "9fbe8fe8ca90c62c259c5894bf96d02ac31209b9"

if len(sys.argv) != 2:
    raise SystemExit("usage: normalize-sukisu-40901-native-policy.py <ksu-root>")

ksu_root = Path(sys.argv[1]).resolve()
if not ksu_root.is_dir():
    raise SystemExit(f"SukiSU tree is missing: {ksu_root}")

head = subprocess.check_output(
    ["git", "-C", str(ksu_root), "rev-parse", "HEAD"], text=True
).strip()
if head != EXPECTED_PIN:
    raise SystemExit(f"SukiSU git HEAD mismatch: expected {EXPECTED_PIN}, got {head}")

# Restore the native setuid-hook API header. The generic SUSFS direct-hook patch
# removes this prototype because it calls setresuid from common/kernel code
# instead of SukiSU 40901's syscall_event_bridge.
setuid_h_rel = "kernel/hook/setuid_hook.h"
setuid_h = ksu_root / setuid_h_rel
if not setuid_h.is_file():
    raise SystemExit(f"SukiSU setuid header is missing: {setuid_h}")
pinned_setuid_h = subprocess.check_output(
    ["git", "-C", str(ksu_root), "show", f"{EXPECTED_PIN}:{setuid_h_rel}"], text=True
)
prototype = "int ksu_handle_setresuid(uid_t old_uid, uid_t new_uid);"
if pinned_setuid_h.count(prototype) != 1:
    raise SystemExit("Pinned SukiSU 40901 setuid header lost the native hook-manager prototype")
setuid_h.write_text(pinned_setuid_h, encoding="utf-8")

# Restore only SukiSU 40901's manager-exclusion guard in allowlist.c instead of
# replacing the entire file. This preserves any unrelated SUSFS-compatible
# changes while keeping the native kernel_umount policy contract intact.
allowlist = ksu_root / "kernel/policy/allowlist.c"
if not allowlist.is_file():
    raise SystemExit(f"SukiSU allowlist source is missing: {allowlist}")
text = allowlist.read_text(encoding="utf-8")
manager_guard = (
    "    if (likely(ksu_is_manager_appid_valid()) && unlikely(ksu_get_manager_appid() == uid % PER_USER_RANGE)) {\n"
    "        // we should not umount on manager!\n"
    "        return false;\n"
    "    }\n"
)

pinned_allowlist = subprocess.check_output(
    ["git", "-C", str(ksu_root), "show", f"{EXPECTED_PIN}:kernel/policy/allowlist.c"], text=True
)
if pinned_allowlist.count(manager_guard) != 1:
    raise SystemExit("Pinned SukiSU 40901 allowlist lost the manager umount exclusion guard")

if manager_guard not in text:
    function_anchor = (
        "bool ksu_uid_should_umount(uid_t uid)\n"
        "{\n"
        "    struct app_profile *profile;\n"
        "    bool res;\n"
    )
    if text.count(function_anchor) != 1:
        raise SystemExit("Cannot restore manager umount guard: ksu_uid_should_umount() anchor is not unique")
    text = text.replace(function_anchor, function_anchor + manager_guard, 1)
    print("Restored SukiSU 40901 manager exclusion in ksu_uid_should_umount()")

if text.count(manager_guard) != 1:
    raise SystemExit("SukiSU manager umount exclusion is missing or duplicated after repair")

allowlist.write_text(text, encoding="utf-8")

# Cross-check the native caller/definition contract that will be compiled once
# syscall_event_bridge.o is linked again.
setuid_c = ksu_root / "kernel/hook/setuid_hook.c"
bridge_c = ksu_root / "kernel/hook/syscall_event_bridge.c"
for path in (setuid_c, bridge_c):
    if not path.is_file():
        raise SystemExit(f"SukiSU native setuid caller/definition source is missing: {path}")
if setuid_c.read_text(encoding="utf-8").count("int ksu_handle_setresuid(uid_t old_uid, uid_t new_uid)") != 1:
    raise SystemExit("SukiSU native setuid implementation does not match the restored two-argument API")
if "ksu_handle_setresuid(old_uid, current_uid().val);" not in bridge_c.read_text(encoding="utf-8"):
    raise SystemExit("SukiSU syscall event bridge no longer calls the native two-argument setuid handler")

print("Restored and verified SukiSU 40901 setuid API and manager umount policy contracts")
