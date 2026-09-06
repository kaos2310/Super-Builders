#!/usr/bin/env python3
"""Normalize Simonpunk's modern SUSFS reboot dispatcher for local adapters.

SUSFS v2.3.0 installs ksu_handle_sys_reboot() in current SukiSU layouts.
The enhanced SUSFS + ZeroMount compatibility code in this tree deliberately
extends a narrower ksu_handle_susfs_cmd() switch.  Extract the exact pinned
SUSFS switch into that helper and delegate to it instead of duplicating the
command table by hand.
"""
from pathlib import Path
import re
import sys
import textwrap

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
HELPER = "int ksu_handle_susfs_cmd(unsigned int cmd, void __user **arg)\n"
REBOOT = "int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg)\n"


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
