#!/usr/bin/env python3
"""Keep fs/open.c SUSFS hooks without widening its genksyms type graph.

The pinned SUSFS v2.3.0 patch adds SUSFS helper headers to fs/open.c.  The same
SUSFS pin is CRC-exact on the Samsung DZH2 / 6.1.145 strict build, but on the
6.1.162 common tree its transitive include graph makes struct uts_namespace and
struct kstatfs complete during genksyms.  The successful DZH2 fs/open.symtypes
keeps both types opaque; the widened 6.1.162 graph changes nonseekable_open().

Keep the narrow <linux/susfs_def.h> header visible to the real compiler while
excluding it from the __GENKSYMS__ pass.  This preserves the SUSFS runtime code
and restores the stock Samsung KMI type visibility instead of bypassing the CRC
gate.

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
    narrow_block = (
        "#ifdef CONFIG_KSU_SUSFS\n"
        "#include <linux/susfs_def.h>\n"
        "#endif\n"
    )
    genksyms_safe_block = (
        "#if defined(CONFIG_KSU_SUSFS) && !defined(__GENKSYMS__)\n"
        "#include <linux/susfs_def.h>\n"
        "#endif\n"
    )

    broad_count = text.count(broad_block)
    broad_include_count = text.count("#include <linux/susfs.h>")
    if broad_include_count == 0:
        pass
    elif broad_count == 1 and broad_include_count == 1:
        text = text.replace(broad_block, "", 1)
    else:
        fail(
            "expected at most one CONFIG_KSU_SUSFS umbrella include block; "
            f"found include_count={broad_include_count}, block_count={broad_count}"
        )

    narrow_count = text.count(narrow_block)
    safe_count = text.count(genksyms_safe_block)
    if safe_count == 1 and narrow_count == 0:
        already_normalized = True
    elif safe_count == 0 and narrow_count == 1:
        text = text.replace(narrow_block, genksyms_safe_block, 1)
        already_normalized = False
    else:
        fail(
            "expected exactly one narrow SUSFS definitions include block; "
            f"found plain={narrow_count}, genksyms_safe={safe_count}"
        )

    required = (
        "#include <linux/susfs_def.h>",
        "!defined(__GENKSYMS__)",
        "extern bool susfs_is_current_proc_umounted(void);",
        "extern bool susfs_is_hidden_name(const char *name, int namlen, uid_t caller_uid);",
        "extern bool susfs_check_unicode_bypass(const char __user *filename);",
        "susfs_is_hidden_name(",
        "susfs_check_unicode_bypass(",
    )
    for marker in required:
        if marker not in text:
            fail(f"required KMI-safe SUSFS marker is missing: {marker}")

    if "#include <linux/susfs.h>" in text:
        fail("broad <linux/susfs.h> include survived normalization")
    if text.count("#include <linux/susfs_def.h>") != 1:
        fail("narrow <linux/susfs_def.h> include is missing or duplicated")
    if text.count(genksyms_safe_block) != 1:
        fail("narrow SUSFS header is not protected from __GENKSYMS__")

    # The enhanced hooks must remain active; this is a KMI type-visibility
    # correction, not a feature bypass.
    if text.count("extern bool susfs_is_hidden_name(") != 1:
        fail("hidden-name declaration is missing or duplicated")
    if text.count("extern bool susfs_check_unicode_bypass(") != 1:
        fail("unicode-filter declaration is missing or duplicated")

    path.write_text(text, encoding="utf-8")
    state = "already normalized" if already_normalized else "normalized"
    print(
        "Verified KMI-neutral SUSFS fs/open.c: "
        f"{state}; runtime header retained, __GENKSYMS__ graph isolated, "
        "enhanced hooks retained"
    )


if __name__ == "__main__":
    main()
