#!/usr/bin/env python3
"""Normalize Simonpunk's modern SUSFS reboot dispatcher for local adapters.

SUSFS v2.3.0 installs ksu_handle_sys_reboot() in current SukiSU layouts.
The enhanced SUSFS + ZeroMount compatibility code in this tree deliberately
extends a narrower ksu_handle_susfs_cmd() switch. Extract the exact pinned
SUSFS switch into that helper and delegate to it instead of duplicating the
command table by hand.

The pinned Simonpunk KernelSU bridge also carries core/init.c hunks from a
nearby KernelSU/SukiSU layout. Some of those hunks still apply with fuzz to
SukiSU Ultra 40901 but silently remove native 40901 lifecycle declarations.
Restore core/init.c from the exact checked-out SukiSU commit and port only the
SUSFS include + susfs_init() call structurally.
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


def repair_sukisu_init(dispatch_path: Path) -> None:
    ksu_root = dispatch_path.parents[2]
    init_path = ksu_root / "kernel/core/init.c"
    if not init_path.is_file():
        raise SystemExit(f"SukiSU core/init.c missing: {init_path}")

    try:
        pristine = subprocess.run(
            ["git", "-C", str(ksu_root), "show", "HEAD:kernel/core/init.c"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or str(exc)
        raise SystemExit(f"cannot restore pinned SukiSU core/init.c: {detail}") from exc

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

    required = (
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
    missing = [token for token in required if token not in pristine]
    if missing:
        raise SystemExit(
            "restored SukiSU 40901 core/init.c is missing lifecycle tokens: " + ", ".join(missing)
        )

    if pristine.count("#include <linux/susfs.h>") != 1:
        raise SystemExit("SUSFS include is missing or duplicated after SukiSU init restoration")
    if pristine.count("susfs_init();") != 1:
        raise SystemExit("susfs_init() is missing or duplicated after SukiSU init restoration")

    init_path.write_text(pristine, encoding="utf-8")
    print("Restored pinned SukiSU 40901 core/init.c lifecycle and structurally re-added SUSFS init")


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


repair_sukisu_init(path)

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
