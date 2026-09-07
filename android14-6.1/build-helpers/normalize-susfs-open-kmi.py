#!/usr/bin/env python3
"""Keep fs/open.c SUSFS hooks without widening its genksyms type graph.

The enhanced SUSFS patch adds <linux/susfs.h> to fs/open.c.  That umbrella
header exposes complete VFS-adjacent types that Samsung's stock translation
unit keeps incomplete, which changes the CRC of exported nonseekable_open().
fs/open.c already has the narrow SUSFS definitions header and explicit
prototypes for the enhanced hooks, so the umbrella include is unnecessary.

This normalizer is intentionally fail-closed: it only accepts the expected
post-enhanced-patch layout and verifies the hook declarations before writing.
"""

from pathlib import Path
import sys


def fail(message: str) -> None:
    raise SystemExit(f"SUSFS fs/open.c KMI normalization failed: {message}")


def main() -> None:
    if len(sys.argv) != 2:
        fail("usage: normalize-susfs-open-kmi.py <kernel-common-tree>")

    common = Path(sys.argv[1])
    path = common / "fs/open.c"
    if not path.is_file():
        fail(f"missing source: {path}")

    text = path.read_text(encoding="utf-8")

    broad_block = (
        "#ifdef CONFIG_KSU_SUSFS\n"
        "#include <linux/susfs.h>\n"
        "#endif\n"
    )
    broad_count = text.count(broad_block)
    include_count = text.count("#include <linux/susfs.h>")

    if include_count == 0:
        # Idempotent only when the expected narrow ABI surface is already
        # present.  Do not silently accept an unrelated source layout.
        already_normalized = True
    elif broad_count == 1 and include_count == 1:
        text = text.replace(broad_block, "", 1)
        already_normalized = False
    else:
        fail(
            "expected exactly one CONFIG_KSU_SUSFS umbrella include block; "
            f"found include_count={include_count}, block_count={broad_count}"
        )

    required = (
        "#include <linux/susfs_def.h>",
        "extern bool susfs_is_current_proc_umounted(void);",
        "extern bool susfs_is_hidden_name(const char *name, int namlen, uid_t caller_uid);",
        "extern bool susfs_check_unicode_bypass(const char __user *filename);",
        "susfs_is_hidden_name(",
        "susfs_check_unicode_bypass(",
    )
    for marker in required:
        if marker not in text:
            fail(f"required narrow SUSFS marker is missing: {marker}")

    if "#include <linux/susfs.h>" in text:
        fail("broad <linux/susfs.h> include survived normalization")

    # The enhanced hooks must remain active; this is a KMI include-surface
    # correction, not a feature bypass.
    if text.count("extern bool susfs_is_hidden_name(") != 1:
        fail("hidden-name declaration is missing or duplicated")
    if text.count("extern bool susfs_check_unicode_bypass(") != 1:
        fail("unicode-filter declaration is missing or duplicated")

    path.write_text(text, encoding="utf-8")
    state = "already normalized" if already_normalized else "normalized"
    print(
        "Verified KMI-neutral SUSFS fs/open.c: "
        f"{state}; umbrella header removed, enhanced hooks retained"
    )


if __name__ == "__main__":
    main()
