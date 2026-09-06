#!/usr/bin/env python3
"""Normalize Simonpunk's modern SUSFS reboot dispatcher for local adapters.

SUSFS v2.3.0 installs ksu_handle_sys_reboot() in current SukiSU layouts.
The enhanced SUSFS + ZeroMount compatibility code in this tree deliberately
extends a narrower ksu_handle_susfs_cmd() switch. Extract the exact pinned
SUSFS switch into that helper and delegate to it instead of duplicating the
command table by hand.

The pinned Simonpunk KernelSU bridge also carries lifecycle/profile hunks from
a nearby KernelSU/SukiSU layout. Some of those hunks still apply with fuzz to
SukiSU Ultra 40901 but silently remove native 40901 declarations and helpers.
Restore core/init.c plus policy/app_profile.[ch] from the exact checked-out
SukiSU commit, then port only the SUSFS init into core/init.c structurally.
"""
from pathlib import Path
import re
import subprocess
import sys
import textwrap

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
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
        "ksu_lsm_hook_init();",
        "ksu_app_profile_init();",
        "ksu_syscall_hook_manager_init();",
        "ksu_syscall_hook_manager_exit();",
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


repair_sukisu_lifecycle(path)

if HELPER not in text:
    if text.count(REBOOT) != 1:
        raise SystemExit(f"expected one ksu_handle_sys_reboot(), found {text.count(REBOOT)}")
    reboot_at = text.index(REBOOT)
    reboot_open = text.find("{", reboot_at + len(REBOOT))
    reboot_close = close_brace(text, reboot_open)

    sus = re.compile(
        r"(?m)^(?P<i>[ \t]*)if \(magic2 == SUSFS_MAGIC && current_uid\(\)\.val == 0\) \{"
    ).search(text, reboot_open, reboot_close)
    if not sus:
        raise SystemExit("SUSFS_MAGIC branch missing from ksu_handle_sys_reboot()")
    sus_open = text.find("{", sus.start(), sus.end() + 1)
    sus_close = close_brace(text, sus_open)

    sw = re.search(r"switch\s*\(cmd\)\s*\{", text[sus_open + 1:sus_close])
    if not sw:
        raise SystemExit("SUSFS command switch missing")
    sw_at = sus_open + 1 + sw.start()
    sw_open = text.find("{", sw_at, sus_close)
    sw_close = close_brace(text, sw_open)
    switch = textwrap.dedent(text[sw_at:sw_close + 1]).strip() + "\n"
    switch = brace_path_case(switch, "CMD_SUSFS_ADD_SUS_PATH", "susfs_add_sus_path")
    switch = brace_path_case(switch, "CMD_SUSFS_ADD_SUS_PATH_LOOP", "susfs_add_sus_path_loop")

    helper = HELPER + "{\n" + textwrap.indent(switch, "    ") + "}\n\n"
    indent = sus.group("i")
    delegate = (
        f"{indent}if (magic2 == SUSFS_MAGIC && current_uid().val == 0) {{\n"
        f"{indent}    return ksu_handle_susfs_cmd(cmd, arg);\n"
        f"{indent}}}"
    )
    text = text[:sus.start()] + delegate + text[sus_close + 1:]
    reboot_at = text.index(REBOOT)
    text = text[:reboot_at] + helper + text[reboot_at:]

text = brace_path_case(text, "CMD_SUSFS_ADD_SUS_PATH", "susfs_add_sus_path")
text = brace_path_case(text, "CMD_SUSFS_ADD_SUS_PATH_LOOP", "susfs_add_sus_path_loop")

for token in (
    HELPER.strip(), REBOOT.strip(),
    "return ksu_handle_susfs_cmd(cmd, arg);",
    "case CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY:",
    "case CMD_SUSFS_ADD_SUS_PATH: {",
    "case CMD_SUSFS_ADD_SUS_PATH_LOOP: {",
):
    if token not in text:
        raise SystemExit(f"normalized dispatcher missing {token!r}")

path.write_text(text, encoding="utf-8")
print("Normalized SukiSU SUSFS reboot dispatcher for enhanced SUSFS/ZeroMount")
