#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

HANDLER_NEEDLE = """    int ret = ksu_handle_dynamic_manager(&cmd);\n"""
HANDLER_REPLACEMENT = """    /*\n     * KSU_IOCTL_DYNAMIC_MANAGER carries both read and write operations.\n     * The manager UI legitimately uses GET without first becoming uid 0,\n     * while SET/SET_SYNCHRONOUS/WIPE change kernel manager identity state.\n     * Keep those mutating operations root-only even though the dispatcher\n     * now lets a registered manager reach this handler.\n     */\n    if (cmd.operation != DYNAMIC_MANAGER_OP_GET && !only_root()) {\n        pr_warn(\"dynamic_manager: mutating operation %u denied for uid=%d\\n\",\n                cmd.operation, ksu_get_uid_t(current_uid()));\n        return -EPERM;\n    }\n\n    int ret = ksu_handle_dynamic_manager(&cmd);\n"""

TABLE_NEEDLE = """    { \n        .cmd = KSU_IOCTL_DYNAMIC_MANAGER,\n        .name = \"SET_DYNAMIC_MANAGER\",\n        .handler = do_dynamic_manager,\n        .perm_check = only_root \n    },\n"""
TABLE_REPLACEMENT = """    { \n        .cmd = KSU_IOCTL_DYNAMIC_MANAGER,\n        .name = \"DYNAMIC_MANAGER\",\n        .handler = do_dynamic_manager,\n        .perm_check = manager_or_root \n    },\n"""

MARKER = "KSU_IOCTL_DYNAMIC_MANAGER carries both read and write operations"


def fail(msg: str) -> None:
    raise SystemExit(f"ERROR: {msg}")


def verify(text: str) -> None:
    required = [
        MARKER,
        "cmd.operation != DYNAMIC_MANAGER_OP_GET && !only_root()",
        '.name = "DYNAMIC_MANAGER"',
        ".perm_check = manager_or_root",
    ]
    for item in required:
        if item not in text:
            fail(f"post-patch verification missing: {item}")

    dynamic_block_start = text.find(".cmd = KSU_IOCTL_DYNAMIC_MANAGER")
    dynamic_block_end = text.find("},", dynamic_block_start)
    if dynamic_block_start < 0 or dynamic_block_end < 0:
        fail("dynamic-manager dispatch table entry not found after patch")
    dynamic_block = text[dynamic_block_start:dynamic_block_end]
    if ".perm_check = only_root" in dynamic_block:
        fail("dynamic-manager dispatcher is still root-only")

    handler_start = text.find("static int do_dynamic_manager")
    handler_end = text.find("static int do_get_managers", handler_start)
    if handler_start < 0 or handler_end < 0:
        fail("do_dynamic_manager handler bounds not found")
    handler = text[handler_start:handler_end]
    if "DYNAMIC_MANAGER_OP_SET" not in text or "DYNAMIC_MANAGER_OP_WIPE" not in text:
        fail("expected mutating dynamic-manager operations are missing from UAPI/source")
    if "!only_root()" not in handler:
        fail("handler does not retain root-only guard for mutating operations")


def patch_dispatch(dispatch: Path) -> None:
    if not dispatch.is_file():
        fail(f"missing ReSukiSU dispatch source: {dispatch}")

    text = dispatch.read_text(encoding="utf-8")

    if MARKER in text:
        verify(text)
        print(f"ReSukiSU dynamic-manager permission fix already present: {dispatch}")
        return

    if text.count(HANDLER_NEEDLE) != 1:
        fail(f"expected exactly one dynamic-manager handler call, found {text.count(HANDLER_NEEDLE)}")
    if text.count(TABLE_NEEDLE) != 1:
        fail(f"expected exactly one root-only dynamic-manager table entry, found {text.count(TABLE_NEEDLE)}")

    text = text.replace(HANDLER_NEEDLE, HANDLER_REPLACEMENT, 1)
    text = text.replace(TABLE_NEEDLE, TABLE_REPLACEMENT, 1)
    verify(text)
    dispatch.write_text(text, encoding="utf-8")
    print(f"Applied operation-aware ReSukiSU dynamic-manager permission fix: {dispatch}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("ksu_root", type=Path, help="Checked-out ReSukiSU source directory")
    args = parser.parse_args()
    patch_dispatch(args.ksu_root / "kernel" / "supercall" / "dispatch.c")


if __name__ == "__main__":
    main()
