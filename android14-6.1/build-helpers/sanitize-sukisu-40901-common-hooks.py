#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: sanitize-sukisu-40901-common-hooks.py <common-tree> <ksu-root>")

COMMON = Path(sys.argv[1]).resolve()
KSU_ROOT = Path(sys.argv[2]).resolve()

TARGETS = {
    "drivers/input/input.c": (
        "ksu_is_input_hook_enabled",
        "ksu_handle_input_handle_event(",
    ),
    "fs/exec.c": (
        "ksu_handle_execveat(",
        "ksu_handle_execveat_sucompat(",
        "ksu_su_compat_enabled",
        "susfs_is_sus_su_hooks_enabled",
        "susfs_is_current_proc_no_su(",
        "susfs_is_sdcard_android_data_not_decrypted",
    ),
    "fs/open.c": (
        "ksu_handle_faccessat(",
        "ksu_su_compat_enabled",
        "susfs_is_sus_su_hooks_enabled",
        "__ksu_is_allow_uid_for_current(",
    ),
    "fs/read_write.c": (
        "ksu_is_init_rc_hook_enabled",
        "ksu_handle_sys_read(",
        "ksu_handle_vfs_read(",
        "susfs_is_sus_su_hooks_enabled",
    ),
    "fs/stat.c": (
        "ksu_is_init_rc_hook_enabled",
        "ksu_handle_vfs_fstat(",
        "ksu_su_compat_enabled",
        "susfs_is_sus_su_hooks_enabled",
        "ksu_handle_stat(",
        "__ksu_is_allow_uid_for_current(",
    ),
    "kernel/sys.c": (
        "ksu_handle_setresuid(",
        "susfs_is_sus_su_hooks_enabled",
    ),
}

OPEN_RE = re.compile(r"^\s*#\s*(?:if|ifdef|ifndef)\b")
ENDIF_RE = re.compile(r"^\s*#\s*endif\b")
KSU_GUARD_RE = re.compile(r"\bCONFIG_KSU(?:_[A-Z0-9_]+)?\b")
PROTECTED = ("zeromount_", "CONFIG_ZEROMOUNT")


def blocks(lines: list[str]) -> list[tuple[int, int, str]]:
    stack: list[tuple[int, str]] = []
    out: list[tuple[int, int, str]] = []
    for idx, line in enumerate(lines):
        if OPEN_RE.match(line):
            stack.append((idx, line))
        elif ENDIF_RE.match(line):
            if not stack:
                raise SystemExit(f"Unmatched #endif at source line {idx + 1}")
            start, opener = stack.pop()
            out.append((start, idx + 1, opener))
    if stack:
        start, opener = stack[-1]
        raise SystemExit(
            f"Unterminated preprocessor block at source line {start + 1}: {opener.strip()}"
        )
    return out


def sanitize_file(rel: str, tokens: tuple[str, ...]) -> int:
    path = COMMON / rel
    if not path.is_file():
        raise SystemExit(f"Missing common source: {rel}")

    original = path.read_text(encoding="utf-8")
    text = original
    removed = 0

    for _pass in range(32):
        lines = text.splitlines(keepends=True)
        candidates: list[tuple[int, int, str, tuple[str, ...]]] = []
        for start, end, opener in blocks(lines):
            if not KSU_GUARD_RE.search(opener):
                continue
            block = "".join(lines[start:end])
            hits = tuple(token for token in tokens if token in block)
            if hits:
                candidates.append((start, end, block, hits))

        if not candidates:
            break

        # Remove the narrowest matching guarded blocks first. This preserves
        # unrelated SukiSU/SUSFS code when a broad CONFIG_KSU wrapper contains
        # a more specific legacy callback sub-block.
        selected: list[tuple[int, int, str, tuple[str, ...]]] = []
        for candidate in sorted(candidates, key=lambda item: (item[1] - item[0], item[0])):
            start, end, block, hits = candidate
            if any(start <= s and end >= e for s, e, _, _ in selected):
                continue
            if any(marker in block for marker in PROTECTED):
                markers = ", ".join(marker for marker in PROTECTED if marker in block)
                raise SystemExit(
                    f"Refusing to remove mixed KSU/ZeroMount block in {rel} "
                    f"(lines {start + 1}-{end}); protected marker(s): {markers}"
                )
            selected.append(candidate)

        if not selected:
            break

        remove_lines: set[int] = set()
        for start, end, _block, hits in selected:
            remove_lines.update(range(start, end))
            removed += 1
            print(
                f"Removed legacy SukiSU-40901-incompatible block from {rel}: "
                f"lines {start + 1}-{end}; token(s)={','.join(hits)}"
            )
        text = "".join(line for idx, line in enumerate(lines) if idx not in remove_lines)
    else:
        raise SystemExit(f"Exceeded reconciliation pass limit for {rel}")

    survivors = [token for token in tokens if token in text]
    if survivors:
        raise SystemExit(
            f"Legacy generic KernelSU/SUSFS hook survived guarded reconciliation in {rel}: "
            + ", ".join(survivors)
        )

    if text != original:
        path.write_text(text, encoding="utf-8")
    return removed


if not COMMON.is_dir():
    raise SystemExit(f"Kernel common tree is missing: {COMMON}")
if not KSU_ROOT.is_dir():
    raise SystemExit(f"SukiSU tree is missing: {KSU_ROOT}")

removed_total = 0
for relative, tokens in TARGETS.items():
    removed_total += sanitize_file(relative, tokens)

# SukiSU 40901's SUSFS setuid marker calls is_zygote() through selinux helpers.
# Keep that dependency explicit before the later verifier runs.
setuid_hook = KSU_ROOT / "kernel/hook/setuid_hook.c"
if setuid_hook.is_file():
    setuid_text = setuid_hook.read_text(encoding="utf-8")
    if "susfs_set_current_proc_umounted();" in setuid_text:
        required_include = '#include "selinux/selinux.h"\n'
        if required_include not in setuid_text:
            anchor = '#include "feature/kernel_umount.h"\n'
            if setuid_text.count(anchor) != 1:
                raise SystemExit(
                    f"Cannot locate unique kernel_umount include in {setuid_hook}: "
                    f"{setuid_text.count(anchor)}"
                )
            setuid_text = setuid_text.replace(anchor, anchor + required_include, 1)
            setuid_hook.write_text(setuid_text, encoding="utf-8")
            print("Added explicit selinux/selinux.h dependency to SukiSU setuid hook")
        if required_include not in setuid_hook.read_text(encoding="utf-8"):
            raise SystemExit("Failed to install SukiSU setuid SELinux dependency")

print(
    "SukiSU Ultra 40901 common-hook reconciliation complete: "
    f"removed_blocks={removed_total}"
)
