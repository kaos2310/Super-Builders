#!/usr/bin/env python3
"""Normalize Simonpunk's modern SUSFS bridge for SukiSU Ultra 40901.

The pinned Simonpunk bridge is based on a nearby KernelSU/SukiSU layout.
Several hunks still apply with fuzz to SukiSU Ultra 40901 but replace native
40901 lifecycle, app-profile, object-manifest and supercall semantics. Preserve
the exact checked-out SukiSU implementation and port only the SUSFS-specific
pieces:
- SUSFS init in core/init.c
- the pinned SukiSU 40901 kernel/Kbuild object manifest
- the pinned SUSFS command switch in supercall/dispatch.c
- the direct reboot entry point required by kernel/reboot.c and local adapters
"""
from pathlib import Path
import re
import subprocess
import sys
import textwrap

path = Path(sys.argv[1])
post_patch_text = path.read_text(encoding="utf-8")
HELPER = "int ksu_handle_susfs_cmd(unsigned int cmd, void __user **arg)\n"
REBOOT = "int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg)\n"


def git_show_pinned(ksu_root: Path, rel: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(ksu_root), "show", f"HEAD:{rel}"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or str(exc)
        raise SystemExit(f"cannot restore pinned SukiSU {rel}: {detail}") from exc


def repair_sukisu_lifecycle(dispatch_path: Path) -> None:
    ksu_root = dispatch_path.parents[2]
    init_path = ksu_root / "kernel/core/init.c"
    profile_h_path = ksu_root / "kernel/policy/app_profile.h"
    profile_c_path = ksu_root / "kernel/policy/app_profile.c"
    for item in (init_path, profile_h_path, profile_c_path):
        if not item.is_file():
            raise SystemExit(f"SukiSU lifecycle source missing: {item}")

    pristine = git_show_pinned(ksu_root, "kernel/core/init.c")
    profile_h = git_show_pinned(ksu_root, "kernel/policy/app_profile.h")
    profile_c = git_show_pinned(ksu_root, "kernel/policy/app_profile.c")

    include_block = "#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs.h>\n#endif\n"
    if "#include <linux/susfs.h>" not in pristine:
        anchors = (
            "#include <linux/moduleparam.h>\n",
            "#include <linux/workqueue.h>\n",
        )
        anchor = next((item for item in anchors if pristine.count(item) == 1), None)
        if anchor is None:
            raise SystemExit("cannot locate unique SukiSU 40901 include anchor in core/init.c")
        pristine = pristine.replace(anchor, anchor + "\n" + include_block, 1)

    if "susfs_init();" not in pristine:
        anchor = "    ksu_feature_init();\n"
        if pristine.count(anchor) != 1:
            raise SystemExit(
                f"expected one ksu_feature_init() anchor in pinned core/init.c, found {pristine.count(anchor)}"
            )
        init_block = (
            "#ifdef CONFIG_KSU_SUSFS\n"
            "    susfs_init();\n"
            "#endif // CONFIG_KSU_SUSFS\n\n"
        )
        pristine = pristine.replace(anchor, init_block + anchor, 1)

    init_required = (
        '#include "policy/app_profile.h"',
        '#include "hook/syscall_hook_manager.h"',
        '#include "hook/lsm_hook.h"',
        "bool ksu_late_loaded;",
        "ksu_init_symbol_resolver();",
        "ksu_syscall_hook_init();",
        "ksu_lsm_hook_init();",
        "ksu_app_profile_init();",
        "ksu_syscall_hook_manager_init();",
        "ksu_syscall_hook_manager_exit();",
        "ksu_lsm_hook_exit();",
        "#include <linux/susfs.h>",
        "susfs_init();",
    )
    missing = [token for token in init_required if token not in pristine]
    if missing:
        raise SystemExit(
            "restored SukiSU 40901 core/init.c is missing lifecycle tokens: " + ", ".join(missing)
        )

    profile_h_required = (
        '#include "linux/init.h"',
        "void escape_to_root_for_init(void);",
        "void __init ksu_app_profile_init(void);",
    )
    missing = [token for token in profile_h_required if token not in profile_h]
    if missing:
        raise SystemExit(
            "restored SukiSU 40901 app_profile.h is missing lifecycle declarations: " + ", ".join(missing)
        )
    if "int escape_to_root_for_init(void);" in profile_h:
        raise SystemExit("foreign SUSFS app_profile.h ABI survived pinned restoration")

    profile_c_required = (
        '#include "hook/patch_memory.h"',
        '#include "infra/symbol_resolver.h"',
        '#include "linux/kallsyms.h"',
        '#include "hook/tp_marker.h"',
        "void escape_to_root_for_init(void)",
        "void __init ksu_app_profile_init(void)",
        "ksu_set_task_tracepoint_flag(t);",
    )
    missing = [token for token in profile_c_required if token not in profile_c]
    if missing:
        raise SystemExit(
            "restored SukiSU 40901 app_profile.c is missing lifecycle implementation: " + ", ".join(missing)
        )
    if "int escape_to_root_for_init(void)" in profile_c:
        raise SystemExit("foreign SUSFS app_profile.c ABI survived pinned restoration")

    if pristine.count("#include <linux/susfs.h>") != 1:
        raise SystemExit("SUSFS include is missing or duplicated after SukiSU init restoration")
    if pristine.count("susfs_init();") != 1:
        raise SystemExit("susfs_init() is missing or duplicated after SukiSU init restoration")

    init_path.write_text(pristine, encoding="utf-8")
    profile_h_path.write_text(profile_h, encoding="utf-8")
    profile_c_path.write_text(profile_c, encoding="utf-8")
    print(
        "Restored pinned SukiSU 40901 init/app-profile lifecycle and structurally re-added SUSFS init"
    )


def repair_sukisu_kbuild(dispatch_path: Path) -> None:
    """Restore the 40901 object graph without undoing workflow version freezing.

    Simonpunk's generic KernelSU patch can successfully fuzz-apply its Kbuild
    hunk while replacing SukiSU 40901's modern split object graph with an older
    one.  The lifecycle/dispatcher normalizers then restore references to the
    modern hook manager, symbol resolver and tracepoint marker, which compiles
    but fails at vmlinux link time because those implementation objects are no
    longer members of kernelsu.o.

    Restore only the object-manifest prefix from the immutable SukiSU pin. Keep
    the remainder of the live Kbuild intact so the workflow's deterministic
    KSU_VERSION / KSU_VERSION_FULL rewrite and any unrelated build metadata are
    preserved.
    """
    ksu_root = dispatch_path.parents[2]
    kbuild_path = ksu_root / "kernel/Kbuild"
    if not kbuild_path.is_file():
        raise SystemExit(f"SukiSU Kbuild is missing: {kbuild_path}")

    pinned = git_show_pinned(ksu_root, "kernel/Kbuild")
    current = kbuild_path.read_text(encoding="utf-8")
    end_marker = "obj-$(CONFIG_KSU) += kernelsu.o\n"

    pinned_end = pinned.find(end_marker)
    current_end = current.find(end_marker)
    if pinned_end < 0 or current_end < 0:
        raise SystemExit("cannot locate kernelsu.o object-manifest terminator in SukiSU Kbuild")
    pinned_end += len(end_marker)
    current_end += len(end_marker)

    pinned_manifest = pinned[:pinned_end]
    current_suffix = current[current_end:]

    required_objects = (
        "kernelsu-objs := core/init.o",
        "kernelsu-objs += hook/lsm_hook.o",
        "kernelsu-objs += hook/syscall_hook.o",
        "kernelsu-objs += hook/syscall_hook_manager.o",
        "kernelsu-objs += hook/tp_marker.o",
        "kernelsu-objs += infra/symbol_resolver.o",
        "kernelsu-objs += supercall/dispatch.o",
        "obj-$(CONFIG_KPM) += kpm/compact.o",
        "obj-$(CONFIG_KPM) += kpm/kpm.o",
        "obj-$(CONFIG_KPM) += kpm/super_access.o",
        "obj-$(CONFIG_KSU) += kernelsu.o",
    )
    missing = [token for token in required_objects if token not in pinned_manifest]
    if missing:
        raise SystemExit(
            "pinned SukiSU 40901 Kbuild lost required object entries: " + ", ".join(missing)
        )

    # SUSFS itself is built from common/fs and does not require a private
    # drivers/kernelsu object. Refuse to silently discard an unexpected SUSFS
    # object addition if a future upstream patch starts depending on one.
    current_prefix = current[:current_end]
    unexpected_susfs_objects = [
        line
        for line in current_prefix.splitlines()
        if "SUSFS" in line and ("-objs" in line or "obj-" in line)
    ]
    if unexpected_susfs_objects:
        raise SystemExit(
            "generic SUSFS patch introduced Kbuild object entries that need an explicit 40901 port: "
            + "; ".join(unexpected_susfs_objects)
        )

    normalized = pinned_manifest + current_suffix
    for token in required_objects:
        if normalized.count(token) != 1:
            raise SystemExit(f"normalized SukiSU Kbuild does not contain exactly one required entry: {token}")

    # The setup step freezes these fields before SUSFS is applied. They live in
    # the preserved suffix and must survive object-manifest restoration.
    for token in ("KSU_VERSION := 40901", "KSU_VERSION_FULL := v4.2.0-40901"):
        if token not in current_suffix:
            raise SystemExit(f"workflow-frozen SukiSU build identity missing before Kbuild normalization: {token}")
        if token not in normalized:
            raise SystemExit(f"workflow-frozen SukiSU build identity lost during Kbuild normalization: {token}")

    kbuild_path.write_text(normalized, encoding="utf-8")
    print(
        "Restored pinned SukiSU 40901 Kbuild object graph while preserving frozen build identity"
    )


def close_brace(src: str, opening: int) -> int:
    depth = 0
    for pos in range(opening, len(src)):
        if src[pos] == "{":
            depth += 1
        elif src[pos] == "}":
            depth -= 1
            if depth == 0:
                return pos
    raise SystemExit("unterminated C brace block")


def brace_path_case(src: str, command: str, function: str) -> str:
    if re.search(rf"(?m)^[ \t]*case {command}: \{{$", src):
        return src
    pattern = re.compile(
        rf"(?m)^(?P<i>[ \t]*)case {command}:\n"
        rf"(?P=i)[ \t]+{function}\(arg\);\n"
        rf"(?P=i)[ \t]+return 0;\n"
    )
    match = pattern.search(src)
    if not match:
        raise SystemExit(f"cannot normalize {command}")
    indent = match.group("i")
    replacement = (
        f"{indent}case {command}: {{\n"
        f"{indent}    {function}(arg);\n"
        f"{indent}    return 0;\n"
        f"{indent}}}\n"
    )
    return src[:match.start()] + replacement + src[match.end():]


def extract_pinned_susfs_switch(src: str) -> str:
    if src.count(REBOOT) != 1:
        raise SystemExit(f"expected one patched ksu_handle_sys_reboot(), found {src.count(REBOOT)}")
    reboot_at = src.index(REBOOT)
    reboot_open = src.find("{", reboot_at + len(REBOOT))
    reboot_close = close_brace(src, reboot_open)

    sus = re.compile(
        r"(?m)^(?P<i>[ \t]*)if \(magic2 == SUSFS_MAGIC && current_uid\(\)\.val == 0\) \{"
    ).search(src, reboot_open, reboot_close)
    if not sus:
        raise SystemExit("SUSFS_MAGIC branch missing from patched ksu_handle_sys_reboot()")
    sus_open = src.find("{", sus.start(), sus.end() + 1)
    sus_close = close_brace(src, sus_open)

    sw = re.search(r"switch\s*\(cmd\)\s*\{", src[sus_open + 1:sus_close])
    if not sw:
        raise SystemExit("SUSFS command switch missing from patched dispatcher")
    sw_at = sus_open + 1 + sw.start()
    sw_open = src.find("{", sw_at, sus_close)
    sw_close = close_brace(src, sw_open)
    switch = textwrap.dedent(src[sw_at:sw_close + 1]).strip() + "\n"
    switch = brace_path_case(switch, "CMD_SUSFS_ADD_SUS_PATH", "susfs_add_sus_path")
    switch = brace_path_case(switch, "CMD_SUSFS_ADD_SUS_PATH_LOOP", "susfs_add_sus_path_loop")
    return switch


def rebuild_pinned_dispatch(dispatch_path: Path, patched: str) -> str:
    ksu_root = dispatch_path.parents[2]
    switch = extract_pinned_susfs_switch(patched)
    pristine = git_show_pinned(ksu_root, "kernel/supercall/dispatch.c")

    native_required = (
        '#include "hook/tp_marker.h"',
        "if (ksu_late_loaded) {",
        "ksu_mark_running_process();",
        "case KSU_MARK_REFRESH:",
        "ksu_set_task_mark(cmd.pid, true);",
        "ksu_set_task_mark(cmd.pid, false);",
    )
    missing = [token for token in native_required if token not in pristine]
    if missing:
        raise SystemExit(
            "pinned SukiSU 40901 dispatcher is missing native semantics: " + ", ".join(missing)
        )

    if "#include <linux/susfs.h>" not in pristine:
        anchor = "#include <linux/thread_info.h>\n"
        if pristine.count(anchor) != 1:
            raise SystemExit(
                f"expected one thread_info include in pinned dispatcher, found {pristine.count(anchor)}"
            )
        pristine = pristine.replace(anchor, anchor + "#include <linux/susfs.h>\n", 1)

    dispatcher = (
        HELPER
        + "{\n"
        + textwrap.indent(switch, "    ")
        + "}\n\n"
        + REBOOT
        + "{\n"
        + "    if (magic1 != KSU_INSTALL_MAGIC1)\n"
        + "        return -EINVAL;\n"
        + "    if (magic2 == SUSFS_MAGIC && current_uid().val == 0)\n"
        + "        return ksu_handle_susfs_cmd(cmd, arg);\n"
        + "    return -EINVAL;\n"
        + "}\n\n"
    )
    anchor = "static int do_nuke_ext4_sysfs(void __user *arg)\n"
    if pristine.count(anchor) != 1:
        raise SystemExit(
            f"expected one supercall insertion anchor in pinned dispatcher, found {pristine.count(anchor)}"
        )
    pristine = pristine.replace(anchor, dispatcher + anchor, 1)

    final_required = native_required + (
        "#include <linux/susfs.h>",
        HELPER.strip(),
        REBOOT.strip(),
        "return ksu_handle_susfs_cmd(cmd, arg);",
        "case CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY:",
        "case CMD_SUSFS_ADD_SUS_PATH: {",
        "case CMD_SUSFS_ADD_SUS_PATH_LOOP: {",
    )
    missing = [token for token in final_required if token not in pristine]
    if missing:
        raise SystemExit(
            "rebuilt SukiSU 40901 SUSFS dispatcher is missing required semantics: " + ", ".join(missing)
        )

    print("Restored pinned SukiSU 40901 supercall semantics and structurally injected SUSFS reboot ABI")
    return pristine


repair_sukisu_lifecycle(path)
repair_sukisu_kbuild(path)
text = rebuild_pinned_dispatch(path, post_patch_text)

path.write_text(text, encoding="utf-8")
print("Normalized SukiSU 40901 lifecycle/Kbuild/dispatcher for enhanced SUSFS/ZeroMount")
