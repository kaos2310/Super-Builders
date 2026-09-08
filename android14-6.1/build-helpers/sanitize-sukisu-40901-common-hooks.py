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


def function_span(text: str, signature_re: str, label: str) -> tuple[int, int]:
    match = re.search(signature_re, text, flags=re.MULTILINE)
    if not match:
        raise SystemExit(f"Cannot locate {label}")
    brace = text.find("{", match.end())
    if brace < 0:
        raise SystemExit(f"Cannot locate opening brace for {label}")

    depth = 0
    for pos in range(brace, len(text)):
        char = text[pos]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = pos + 1
                if end < len(text) and text[end] == "\n":
                    end += 1
                return match.start(), end
    raise SystemExit(f"Cannot locate closing brace for {label}")


def normalize_open_faccessat() -> None:
    """Repair residue left by removing the generic KSU faccessat callback.

    Simonpunk's SUSFS bridge rewrites do_faccessat around a struct filename /
    generic KSU callback path. SukiSU 40901 owns faccessat through its native
    syscall hook manager. Removing the generic callback can therefore leave an
    orphan fname declaration and, on Samsung 6.1, the retry label without the
    original user_path_at() assignment. Restore that AOSP path fail-closed while
    retaining all SUSFS VFS/Unicode/hidden-name functionality.
    """
    path = COMMON / "fs/open.c"
    text = path.read_text(encoding="utf-8")
    start, end = function_span(
        text,
        r"^static\s+(?:long|int)\s+do_faccessat\s*\(",
        "fs/open.c do_faccessat()",
    )
    func = text[start:end]
    changed = False

    if "ksu_handle_faccessat(" in func:
        raise SystemExit("Generic ksu_handle_faccessat() survived inside do_faccessat()")

    # The #113 compile log proved that the prior guarded-block sanitizer could
    # leave this declaration after deleting every use of fname.
    if re.search(r"\bfname\b", func):
        fname_uses = len(re.findall(r"\bfname\b", func))
        if fname_uses == 1:
            func, count = re.subn(
                r"^[ \t]*struct\s+filename\s*\*\s*fname\s*=\s*NULL\s*;\s*\n",
                "",
                func,
                count=1,
                flags=re.MULTILINE,
            )
            if count != 1:
                raise SystemExit(
                    "Orphan fname remains in do_faccessat(), but its declaration is not recognized"
                )
            changed = True
            print("Removed orphan generic-KSU fname declaration from fs/open.c do_faccessat()")
        else:
            raise SystemExit(
                f"Unexpected fname residue in do_faccessat(): {fname_uses} references"
            )

    lookup_assignments = (
        "res = user_path_at(dfd, filename, lookup_flags, &path);",
        "res = filename_lookup(dfd, filename, lookup_flags, &path, NULL);",
    )
    if not any(token in func for token in lookup_assignments):
        retry_count = len(re.findall(r"^[ \t]*retry:\s*$", func, flags=re.MULTILINE))
        if retry_count != 1:
            raise SystemExit(
                "do_faccessat() lost its path lookup and does not have exactly one retry label"
            )
        func, count = re.subn(
            r"(^[ \t]*retry:\s*\n)",
            r"\1\tres = user_path_at(dfd, filename, lookup_flags, &path);\n",
            func,
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise SystemExit("Failed to restore user_path_at() in do_faccessat()")
        changed = True
        print("Restored native AOSP user_path_at() assignment in fs/open.c do_faccessat()")

    # Preserve the narrow declaration without reintroducing linux/susfs.h.
    # Run 34168189986 restored that umbrella header AFTER KMI normalization,
    # exposing uts_namespace/kstatfs to genksyms and changing nonseekable_open.
    unicode_decl = "extern bool susfs_check_unicode_bypass(const char __user *filename);"
    if "susfs_check_unicode_bypass(" in text:
        susfs_header = COMMON / "include/linux/susfs.h"
        if not susfs_header.is_file():
            raise SystemExit("SUSFS header is missing while Unicode filter is active")
        if unicode_decl.removeprefix("extern ") not in susfs_header.read_text(encoding="utf-8"):
            raise SystemExit("SUSFS header lacks susfs_check_unicode_bypass() declaration")

        if unicode_decl not in text:
            include_block = (
                "#ifdef CONFIG_KSU_SUSFS\n"
                f"{unicode_decl}\n"
                "#endif\n"
            )
            anchors = (
                '#include "internal.h"\n',
                "#include <linux/mnt_idmapping.h>\n",
                "#include <linux/compat.h>\n",
            )
            anchor = next((item for item in anchors if text.count(item) == 1), None)
            if anchor is None:
                raise SystemExit("Cannot locate a unique fs/open.c SUSFS include anchor")
            text = text.replace(anchor, anchor + "\n" + include_block, 1)
            changed = True
            print("Restored narrow fs/open.c Unicode filter declaration")

    if changed:
        fresh_start, fresh_end = function_span(
            text,
            r"^static\s+(?:long|int)\s+do_faccessat\s*\(",
            "fs/open.c do_faccessat() after header reconciliation",
        )
        current_func = text[fresh_start:fresh_end]
        if current_func != func:
            text = text[:fresh_start] + func + text[fresh_end:]
        path.write_text(text, encoding="utf-8")

    final = path.read_text(encoding="utf-8")
    fstart, fend = function_span(
        final,
        r"^static\s+(?:long|int)\s+do_faccessat\s*\(",
        "final fs/open.c do_faccessat()",
    )
    final_func = final[fstart:fend]
    if re.search(r"\bfname\b", final_func):
        raise SystemExit("Orphan fname survived final do_faccessat() reconciliation")
    if not any(token in final_func for token in lookup_assignments):
        raise SystemExit("Final do_faccessat() has no initialized path lookup")
    if "susfs_check_unicode_bypass(" in final and final.count(unicode_decl) != 1:
        raise SystemExit("Final fs/open.c Unicode filter needs exactly one narrow declaration")


def normalize_sukisu_init_escape_api() -> None:
    """Keep the exact pinned SukiSU 40901 void API and adapt SUSFS call sites."""
    sucompat = KSU_ROOT / "kernel/feature/sucompat.c"
    app_c = KSU_ROOT / "kernel/policy/app_profile.c"
    app_h = KSU_ROOT / "kernel/policy/app_profile.h"
    for path in (sucompat, app_c, app_h):
        if not path.is_file():
            raise SystemExit(f"Missing pinned SukiSU source: {path}")

    app_c_text = app_c.read_text(encoding="utf-8")
    app_h_text = app_h.read_text(encoding="utf-8")
    if not re.search(r"^void\s+escape_to_root_for_init\s*\(void\)\s*$", app_c_text, re.MULTILINE):
        raise SystemExit(
            "Pinned SukiSU 40901 escape_to_root_for_init() implementation is not the expected void API"
        )
    if "void escape_to_root_for_init(void);" not in app_h_text:
        raise SystemExit(
            "Pinned SukiSU 40901 app_profile.h does not expose the expected void escape API"
        )
    if "int escape_to_root_for_init(void)" in app_c_text or "int escape_to_root_for_init(void);" in app_h_text:
        raise SystemExit("Simonpunk int escape_to_root_for_init ABI leaked into pinned SukiSU 40901")

    text = sucompat.read_text(encoding="utf-8")
    pattern = re.compile(
        r"(?P<indent>^[ \t]*)ret\s*=\s*escape_to_root_for_init\(\);\s*\n"
        r"(?P=indent)if\s*\(ret\)\s*\{\s*\n"
        r"(?P=indent)[ \t]+pr_err\(\"escape_to_root_for_init\(\) failed: %d\\n\",\s*ret\);\s*\n"
        r"(?P=indent)[ \t]+return\s+ret;\s*\n"
        r"(?P=indent)\}\s*\n",
        re.MULTILINE,
    )
    text, count = pattern.subn(
        r"\g<indent>escape_to_root_for_init();\n\g<indent>ret = 0;\n",
        text,
        count=1,
    )
    if count == 1:
        sucompat.write_text(text, encoding="utf-8")
        print(
            "Adapted Simonpunk sucompat init escape call to pinned SukiSU 40901 void API"
        )
    elif "ret = escape_to_root_for_init();" in text:
        raise SystemExit(
            "Found incompatible escape_to_root_for_init() assignment with unexpected control flow"
        )

    final = sucompat.read_text(encoding="utf-8")
    if "ret = escape_to_root_for_init();" in final:
        raise SystemExit("Incompatible SukiSU init escape assignment survived reconciliation")
    if "ksu_handle_execveat_init(" in final and "escape_to_root_for_init();" not in final:
        raise SystemExit("SUSFS init exec path lost escape_to_root_for_init() entirely")


if not COMMON.is_dir():
    raise SystemExit(f"Kernel common tree is missing: {COMMON}")
if not KSU_ROOT.is_dir():
    raise SystemExit(f"SukiSU tree is missing: {KSU_ROOT}")

removed_total = 0
for relative, tokens in TARGETS.items():
    removed_total += sanitize_file(relative, tokens)

normalize_open_faccessat()
normalize_sukisu_init_escape_api()

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
