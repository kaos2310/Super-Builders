#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

EXPECTED_PIN = "9fbe8fe8ca90c62c259c5894bf96d02ac31209b9"

if len(sys.argv) != 2:
    raise SystemExit("usage: normalize-sukisu-40901-setuid-susfs.py <ksu-root>")

ksu_root = Path(sys.argv[1]).resolve()
if not ksu_root.is_dir():
    raise SystemExit(f"SukiSU tree is missing: {ksu_root}")

# The workflow checks out the immutable SukiSU pin directly but does not create
# a private marker file inside the upstream repository. Treat git HEAD as the
# authoritative source identity. If a marker exists for another caller, verify
# it as an additional consistency check without requiring it to exist.
marker = ksu_root / ".sukisu-ultra-source-pin"
if marker.is_file():
    marked_pin = marker.read_text(encoding="utf-8").strip()
    if marked_pin != EXPECTED_PIN:
        raise SystemExit(
            f"SukiSU source pin marker mismatch: expected {EXPECTED_PIN}, got {marked_pin}"
        )

head = subprocess.check_output(
    ["git", "-C", str(ksu_root), "rev-parse", "HEAD"], text=True
).strip()
if head != EXPECTED_PIN:
    raise SystemExit(f"SukiSU git HEAD mismatch: expected {EXPECTED_PIN}, got {head}")

# Simonpunk's generic SUSFS patch removes SukiSU 40901's late-load declaration
# from kernel/include/ksu.h together with the native late-load implementation.
# The dispatcher/lifecycle normalizer deliberately restores the pinned 40901
# dispatcher and core/init.c, so the matching public declaration must be put
# back as well. Repair only that declaration instead of replacing the whole
# header so any unrelated SUSFS additions remain intact.
ksu_h_rel = "kernel/include/ksu.h"
ksu_h_path = ksu_root / ksu_h_rel
dispatch_path = ksu_root / "kernel/supercall/dispatch.c"
init_path = ksu_root / "kernel/core/init.c"
for item in (ksu_h_path, dispatch_path, init_path):
    if not item.is_file():
        raise SystemExit(f"SukiSU late-load contract source is missing: {item}")

pinned_ksu_h = subprocess.check_output(
    ["git", "-C", str(ksu_root), "show", f"{EXPECTED_PIN}:{ksu_h_rel}"], text=True
)
late_decl = "extern bool ksu_late_loaded;"
if pinned_ksu_h.count(late_decl) != 1:
    raise SystemExit(
        "Pinned SukiSU 40901 ksu.h no longer has exactly one ksu_late_loaded declaration"
    )

ksu_h_text = ksu_h_path.read_text(encoding="utf-8")
dispatch_text = dispatch_path.read_text(encoding="utf-8")
init_text = init_path.read_text(encoding="utf-8")

if "ksu_late_loaded" not in dispatch_text:
    raise SystemExit(
        "Restored SukiSU 40901 dispatcher unexpectedly lost ksu_late_loaded semantics"
    )
if init_text.count("bool ksu_late_loaded;") != 1:
    raise SystemExit(
        "Restored SukiSU 40901 core/init.c does not define ksu_late_loaded exactly once"
    )

if late_decl not in ksu_h_text:
    anchor = "extern struct cred *ksu_cred;\n"
    if ksu_h_text.count(anchor) != 1:
        raise SystemExit(
            "Cannot restore ksu_late_loaded declaration: ksu_cred anchor is missing or duplicated"
        )
    ksu_h_text = ksu_h_text.replace(anchor, anchor + late_decl + "\n", 1)

if ksu_h_text.count(late_decl) != 1:
    raise SystemExit(
        "SukiSU late-load API declaration is missing or duplicated after SUSFS normalization"
    )
ksu_h_path.write_text(ksu_h_text, encoding="utf-8")
print(
    "Restored SukiSU 40901 late-load API contract after generic SUSFS patch "
    "(dispatch declaration + core definition verified)"
)

rel = "kernel/hook/setuid_hook.c"
setuid_hook = ksu_root / rel
kernel_umount = ksu_root / "kernel/feature/kernel_umount.c"
if not setuid_hook.is_file() or not kernel_umount.is_file():
    raise SystemExit("Pinned SukiSU setuid/kernel-umount source set is incomplete")

# setuid_hook.c is one of SukiSU 40901's rebase-sensitive native hook files.
# Simonpunk's generic KernelSU integration currently injects setuid/WebView
# policy that depends on ksu_webview_zygote_umount_enabled, a symbol that does
# not exist in this pinned SukiSU release. Restore the exact pinned SukiSU file
# from git, then add only the SUSFS process-state marker needed by SUSFS.
base = subprocess.check_output(
    ["git", "-C", str(ksu_root), "show", f"{EXPECTED_PIN}:{rel}"], text=True
)

required_base = (
    "int ksu_handle_setresuid(uid_t old_uid, uid_t new_uid)",
    "ksu_handle_umount(old_uid, new_uid);",
    "ksu_kernel_umount_init();",
)
for token in required_base:
    if token not in base:
        raise SystemExit(f"Pinned SukiSU setuid baseline lost required native token: {token}")
if "ksu_webview_zygote_umount_enabled" in base:
    raise SystemExit("Unexpected WebView-umount compatibility symbol exists in pinned SukiSU baseline")

umount_text = kernel_umount.read_text(encoding="utf-8")
for token in (
    "new_uid != WEBVIEW_ZYGOTE_UID",
    "!ksu_uid_should_umount(new_uid) && !is_isolated_process(new_uid)",
    "bool is_zygote_child = is_zygote(current_cred());",
):
    if token not in umount_text:
        raise SystemExit(
            "Pinned SukiSU kernel_umount.c no longer has the expected WebView/isolated policy: "
            + token
        )

text = base

susfs_include = "#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs_def.h>\n#endif\n"
uidgid_anchor = "#include <linux/uidgid.h>\n"
if text.count(uidgid_anchor) != 1:
    raise SystemExit("Cannot locate unique uidgid include in pinned SukiSU setuid_hook.c")
text = text.replace(uidgid_anchor, uidgid_anchor + susfs_include, 1)

selinux_include = '#include "selinux/selinux.h"\n'
feature_anchor = '#include "feature/kernel_umount.h"\n'
if text.count(feature_anchor) != 1:
    raise SystemExit("Cannot locate unique kernel_umount include in pinned SukiSU setuid_hook.c")
text = text.replace(feature_anchor, feature_anchor + selinux_include, 1)

native_anchor = "    ksu_handle_umount(old_uid, new_uid);\n"
if text.count(native_anchor) != 1:
    raise SystemExit(
        f"Expected one native ksu_handle_umount() call, found {text.count(native_anchor)}"
    )

marker_block = (
    native_anchor
    + "\n#ifdef CONFIG_KSU_SUSFS\n"
    + "    /* Mirror SukiSU 40901 kernel_umount.c eligibility for SUSFS state. */\n"
    + "    if ((is_appuid(new_uid) || new_uid == WEBVIEW_ZYGOTE_UID ||\n"
    + "         is_isolated_process(new_uid)) &&\n"
    + "        (ksu_uid_should_umount(new_uid) || is_isolated_process(new_uid)) &&\n"
    + "        is_zygote(current_cred()))\n"
    + "        susfs_set_current_proc_umounted();\n"
    + "#endif\n"
)
text = text.replace(native_anchor, marker_block, 1)

if text.count("susfs_set_current_proc_umounted();") != 1:
    raise SystemExit("SUSFS setuid marker was not installed exactly once")
if "ksu_webview_zygote_umount_enabled" in text:
    raise SystemExit("Generic KernelSU WebView-umount symbol survived setuid normalization")
if text.count("ksu_handle_umount(old_uid, new_uid);") != 1:
    raise SystemExit("SukiSU native kernel-umount dispatch was duplicated or removed")
if text.count("int ksu_handle_setresuid(uid_t old_uid, uid_t new_uid)") != 1:
    raise SystemExit("SukiSU native setresuid handler was duplicated or removed")
if selinux_include not in text or "#include <linux/susfs_def.h>" not in text:
    raise SystemExit("Required SukiSU/SUSFS setuid declarations are incomplete")

setuid_hook.write_text(text, encoding="utf-8")
print(
    "Restored pinned SukiSU 40901 setuid hook and installed native-policy SUSFS marker"
)
