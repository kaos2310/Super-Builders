#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-qcom-vmid-compat.sh <kernel-tree>}"
GUNYAH_DIR="$KERNEL_TREE/drivers/virt/gunyah"
QCOM_SRC="$GUNYAH_DIR/gunyah_qcom.c"
GUNYAH_MAKEFILE="$GUNYAH_DIR/Makefile"
FIRMWARE_MAKEFILE="$KERNEL_TREE/drivers/firmware/Makefile"
MODULES_BZL="$KERNEL_TREE/modules.bzl"
BACKING_SRC="$GUNYAH_DIR/cma_compat.c"
RM_HEADER="$KERNEL_TREE/include/linux/gunyah_rsc_mgr.h"

for f in "$QCOM_SRC" "$GUNYAH_MAKEFILE" "$FIRMWARE_MAKEFILE" "$MODULES_BZL" "$BACKING_SRC" "$RM_HEADER"; do
  test -f "$f" || { echo "FATAL: required e3q Gunyah source missing: $f" >&2; exit 1; }
done

grep -qF 'gh_rm_get_vmid' "$RM_HEADER" || {
  echo 'FATAL: gh_rm_get_vmid declaration is unavailable; refusing SCM VMID patch' >&2
  exit 1
}

python3 - "$QCOM_SRC" "$GUNYAH_MAKEFILE" "$FIRMWARE_MAKEFILE" "$MODULES_BZL" "$BACKING_SRC" <<'PY'
from pathlib import Path
import re
import sys

qcom_path, gunyah_makefile_path, firmware_makefile_path, modules_bzl_path, backing_path = map(Path, sys.argv[1:])
qcom = qcom_path.read_text()
gunyah_makefile = gunyah_makefile_path.read_text()
firmware_makefile = firmware_makefile_path.read_text()
modules_bzl = modules_bzl_path.read_text()
backing = backing_path.read_text()


def function_span(text: str, signature: str) -> tuple[int, int]:
    start = text.find(signature)
    if start < 0:
        raise SystemExit(f"FATAL: cannot locate {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit(f"FATAL: cannot locate opening brace for {signature}")
    depth = 0
    for pos in range(brace, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return start, pos + 1
    raise SystemExit(f"FATAL: unterminated function {signature}")


def patch_func(text: str, signature: str, transform):
    start, end = function_span(text, signature)
    block = text[start:end]
    new = transform(block)
    if new == block:
        raise SystemExit(f"FATAL: no changes while patching {signature}")
    return text[:start] + new + text[end:]


# Qualcomm SCM VMID compatibility. Dynamic RM VMIDs (e.g. 129 on e3q) are
# outside the SCM-managed direct range and must be represented by the RM proxy.
if "static u16 qcom_scm_map_vmid(u16 vmid)" not in qcom:
    anchor = "#define QCOM_SCM_MAX_MANAGED_VMID\t0x3F\n"
    if qcom.count(anchor) != 1:
        raise SystemExit("FATAL: unexpected Qualcomm VMID define layout")
    helper = (
        anchor
        + "\nstatic u16 qcom_scm_map_vmid(u16 vmid)\n"
        + "{\n"
        + "\tif (vmid <= QCOM_SCM_MAX_MANAGED_VMID)\n"
        + "\t\treturn vmid;\n\n"
        + "\treturn QCOM_SCM_RM_MANAGED_VMID;\n"
        + "}\n"
    )
    qcom = qcom.replace(anchor, helper, 1)

if "GH_QCOM_SCM pre_share" not in qcom:
    def patch_pre(block: str) -> str:
        old_decl = "\tint ret = 0, i, n;\n\tu16 vmid;\n"
        new_decl = (
            "\tint ret = 0, i, n;\n"
            "\tu16 self_vmid, vmid;\n\n"
            "\tret = gh_rm_get_vmid(rm, &self_vmid);\n"
            "\tif (ret)\n"
            "\t\treturn ret;\n"
        )
        if block.count(old_decl) != 1:
            raise SystemExit("FATAL: unexpected pre_mem_share declaration layout")
        block = block.replace(old_decl, new_decl, 1)

        acl = re.compile(
            r"\t\tif \(vmid <= QCOM_SCM_MAX_MANAGED_VMID\)\n"
            r"\t\t\tnew_perms\[n\]\.vmid = vmid;\n"
            r"\t\telse\n"
            r"\t\t\tnew_perms\[n\]\.vmid = QCOM_SCM_RM_MANAGED_VMID;\n"
        )
        block, count = acl.subn(
            "\t\tnew_perms[n].vmid = qcom_scm_map_vmid(vmid);\n", block, count=1
        )
        if count != 1:
            raise SystemExit("FATAL: unexpected pre_mem_share ACL VMID mapping")

        old_src = "\tsrc = BIT_ULL(QCOM_SCM_VMID_HLOS);\n"
        new_src = (
            "\tpr_info(\"GH_QCOM_SCM pre_share self_vmid=%u mapped_src_vmid=%u entries=%zu acl=%zu\\n\",\n"
            "\t\tself_vmid, qcom_scm_map_vmid(self_vmid),\n"
            "\t\tmem_parcel->n_mem_entries, mem_parcel->n_acl_entries);\n"
            "\tsrc = BIT_ULL(qcom_scm_map_vmid(self_vmid));\n"
        )
        if block.count(old_src) != 1:
            raise SystemExit("FATAL: expected fixed HLOS source VMID exactly once")
        block = block.replace(old_src, new_src, 1)

        rollback = re.compile(
            r"\t\tif \(vmid <= QCOM_SCM_MAX_MANAGED_VMID\)\n"
            r"\t\t\tsrc \|= BIT_ULL\(vmid\);\n"
            r"\t\telse\n"
            r"\t\t\tsrc \|= BIT_ULL\(QCOM_SCM_RM_MANAGED_VMID\);\n"
        )
        block, count = rollback.subn(
            "\t\tsrc |= BIT_ULL(qcom_scm_map_vmid(vmid));\n", block, count=1
        )
        if count != 1:
            raise SystemExit("FATAL: unexpected pre_mem_share rollback VMID mapping")
        return block

    qcom = patch_func(qcom, "static int qcom_scm_gh_rm_pre_mem_share(", patch_pre)

if "GH_QCOM_SCM post_reclaim" not in qcom:
    def patch_post(block: str) -> str:
        old_decl = "\tint ret = 0, i, n;\n\tu16 vmid;\n"
        new_decl = (
            "\tint ret = 0, i, n;\n"
            "\tu16 self_vmid, vmid;\n\n"
            "\tret = gh_rm_get_vmid(rm, &self_vmid);\n"
            "\tif (ret)\n"
            "\t\treturn ret;\n\n"
            "\tpr_info(\"GH_QCOM_SCM post_reclaim self_vmid=%u mapped_self_vmid=%u entries=%zu acl=%zu\\n\",\n"
            "\t\tself_vmid, qcom_scm_map_vmid(self_vmid),\n"
            "\t\tmem_parcel->n_mem_entries, mem_parcel->n_acl_entries);\n"
        )
        if block.count(old_decl) != 1:
            raise SystemExit("FATAL: unexpected post_mem_reclaim declaration layout")
        block = block.replace(old_decl, new_decl, 1)

        reclaim = re.compile(
            r"\t\tif \(vmid <= QCOM_SCM_MAX_MANAGED_VMID\)\n"
            r"\t\t\tsrc \|= \(1ull << vmid\);\n"
            r"\t\telse\n"
            r"\t\t\tsrc \|= \(1ull << QCOM_SCM_RM_MANAGED_VMID\);\n"
        )
        block, count = reclaim.subn(
            "\t\tsrc |= BIT_ULL(qcom_scm_map_vmid(vmid));\n", block, count=1
        )
        if count != 1:
            raise SystemExit("FATAL: unexpected post_mem_reclaim VMID mapping")
        return block

    qcom = patch_func(qcom, "static int qcom_scm_gh_rm_post_mem_reclaim(", patch_post)

# Keep the final kernel config aligned with Samsung: do not turn on either
# CONFIG_GUNYAH_QCOM_PLATFORM or CONFIG_QCOM_SCM. Instead, force both existing
# vendor_boot modules as build-only objects. qcom-scm supplies the modpost export
# used by gunyah_qcom, while the flashed AnyKernel still contains only Image.
gunyah_conditional = "obj-$(CONFIG_GUNYAH_QCOM_PLATFORM) += gunyah_qcom.o"
gunyah_forced = "obj-m += gunyah_qcom.o # e3q vendor_boot test module; not packaged by AnyKernel"
if gunyah_forced not in gunyah_makefile:
    if gunyah_makefile.count(gunyah_conditional) != 1:
        raise SystemExit("FATAL: expected one conditional gunyah_qcom Makefile target")
    gunyah_makefile = gunyah_makefile.replace(gunyah_conditional, gunyah_forced, 1)

scm_conditional = "obj-$(CONFIG_QCOM_SCM)\t\t+= qcom-scm.o"
scm_forced = "obj-m\t\t\t+= qcom-scm.o # e3q vendor_boot test dependency; not packaged by AnyKernel"
if scm_forced not in firmware_makefile:
    if firmware_makefile.count(scm_conditional) != 1:
        raise SystemExit("FATAL: expected one conditional qcom-scm Makefile target")
    firmware_makefile = firmware_makefile.replace(scm_conditional, scm_forced, 1)

# Kleaf's kernel_aarch64 target validates every produced module against
# module_implicit_outs. Declare the two build-only ARM64 modules explicitly.
module_entries = [
    '    "drivers/firmware/qcom-scm.ko",\n',
    '    "drivers/virt/gunyah/gunyah_qcom.ko",\n',
]
if any(entry.strip() not in modules_bzl for entry in module_entries):
    list_start = modules_bzl.find("_ARM64_GKI_MODULES_LIST = [")
    if list_start < 0:
        raise SystemExit("FATAL: ARM64 GKI module list not found")
    list_end = modules_bzl.find("\n]", list_start)
    if list_end < 0:
        raise SystemExit("FATAL: ARM64 GKI module list terminator not found")
    block = modules_bzl[list_start:list_end]
    if '"arch/arm64/geniezone/gzvm.ko"' not in block:
        raise SystemExit("FATAL: unexpected ARM64 GKI module-list baseline")
    existing = re.findall(r'^\s*"([^"]+\.ko)",\s*$', block, re.MULTILINE)
    wanted = sorted(set(existing + ["drivers/firmware/qcom-scm.ko", "drivers/virt/gunyah/gunyah_qcom.ko"]))
    prefix = modules_bzl[list_start:]
    header_end = prefix.find("# keep sorted\n")
    if header_end < 0 or header_end > (list_end - list_start):
        raise SystemExit("FATAL: ARM64 GKI module-list sorted marker not found")
    content_start = list_start + header_end + len("# keep sorted\n")
    rendered = "".join(f'    "{name}",\n' for name in wanted)
    modules_bzl = modules_bzl[:content_start] + rendered + modules_bzl[list_end:]

# free_contig_range() warns when GUP still owns references. It ultimately drops
# each page with __free_page(); do that directly for the anon-inode allocator ref.
if "__free_page(nth_page(chunk->base, i));" not in backing:
    old = (
        "static void gh_extent_free_one(struct gh_extent_chunk *chunk)\n"
        "{\n"
        "\tunsigned long nr_pages;\n\n"
        "\tif (!chunk || !chunk->base)\n"
        "\t\treturn;\n\n"
        "\tnr_pages = 1UL << chunk->order;\n"
        "\tif (chunk->contig)\n"
        "\t\tfree_contig_range(page_to_pfn(chunk->base), nr_pages);\n"
        "\telse\n"
        "\t\t__free_pages(chunk->base, chunk->order);\n\n"
        "\tchunk->base = NULL;\n"
        "}\n"
    )
    new = (
        "static void gh_extent_free_one(struct gh_extent_chunk *chunk)\n"
        "{\n"
        "\tunsigned long nr_pages;\n"
        "\tunsigned long i;\n\n"
        "\tif (!chunk || !chunk->base)\n"
        "\t\treturn;\n\n"
        "\tnr_pages = 1UL << chunk->order;\n"
        "\tif (chunk->contig) {\n"
        "\t\tfor (i = 0; i < nr_pages; i++)\n"
        "\t\t\t__free_page(nth_page(chunk->base, i));\n"
        "\t} else {\n"
        "\t\t__free_pages(chunk->base, chunk->order);\n"
        "\t}\n\n"
        "\tchunk->base = NULL;\n"
        "}\n"
    )
    if backing.count(old) != 1:
        raise SystemExit("FATAL: unexpected bounded-backing teardown layout")
    backing = backing.replace(old, new, 1)

qcom_path.write_text(qcom)
gunyah_makefile_path.write_text(gunyah_makefile)
firmware_makefile_path.write_text(firmware_makefile)
modules_bzl_path.write_text(modules_bzl)
backing_path.write_text(backing)
PY

# Fail closed on the exact runtime/build fixes we intend to test.
grep -qF 'static u16 qcom_scm_map_vmid(u16 vmid)' "$QCOM_SRC"
grep -qF 'gh_rm_get_vmid(rm, &self_vmid)' "$QCOM_SRC"
grep -qF 'GH_QCOM_SCM pre_share self_vmid=' "$QCOM_SRC"
grep -qF 'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' "$QCOM_SRC"
grep -qF 'new_perms[n].vmid = qcom_scm_map_vmid(vmid);' "$QCOM_SRC"
grep -qF 'GH_QCOM_SCM post_reclaim self_vmid=' "$QCOM_SRC"
grep -qF 'src |= BIT_ULL(qcom_scm_map_vmid(vmid));' "$QCOM_SRC"
grep -qF 'obj-m += gunyah_qcom.o # e3q vendor_boot test module; not packaged by AnyKernel' "$GUNYAH_MAKEFILE"
grep -qF 'qcom-scm.o # e3q vendor_boot test dependency; not packaged by AnyKernel' "$FIRMWARE_MAKEFILE"
grep -qF '"drivers/firmware/qcom-scm.ko",' "$MODULES_BZL"
grep -qF '"drivers/virt/gunyah/gunyah_qcom.ko",' "$MODULES_BZL"
grep -qF '__free_page(nth_page(chunk->base, i));' "$BACKING_SRC"
! grep -qF 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$BACKING_SRC"
grep -qF 'mapping->parcel.n_mem_entries > 8192' "$GUNYAH_DIR/vm_mgr.c"
grep -qF 'ret = -E2BIG;' "$GUNYAH_DIR/vm_mgr.c"

echo 'e3q Gunyah follow-up applied: SCM RM-VMID mapping + safe contig teardown + Kleaf-declared vendor_boot test modules'
