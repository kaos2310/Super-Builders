#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-qcom-vmid-compat.sh <kernel-tree>}"
GUNYAH_DIR="$KERNEL_TREE/drivers/virt/gunyah"
QCOM_SRC="$GUNYAH_DIR/gunyah_qcom.c"
GUNYAH_MAKEFILE="$GUNYAH_DIR/Makefile"
MODULES_BZL="$KERNEL_TREE/modules.bzl"
BACKING_SRC="$GUNYAH_DIR/cma_compat.c"
RM_HEADER="$KERNEL_TREE/include/linux/gunyah_rsc_mgr.h"
RM_RPC="$GUNYAH_DIR/rsc_mgr_rpc.c"
QCOM_SCM_HEADER="$KERNEL_TREE/include/linux/qcom_scm.h"

for f in "$QCOM_SRC" "$GUNYAH_MAKEFILE" "$MODULES_BZL" "$BACKING_SRC" \
         "$RM_HEADER" "$RM_RPC" "$QCOM_SCM_HEADER"; do
  test -f "$f" || { echo "FATAL: required e3q Gunyah source missing: $f" >&2; exit 1; }
done

grep -qF 'gh_rm_get_vmid' "$RM_HEADER" || {
  echo 'FATAL: gh_rm_get_vmid declaration is unavailable' >&2; exit 1;
}
grep -qF 'EXPORT_SYMBOL_GPL(gh_rm_get_vmid);' "$RM_RPC" || {
  echo 'FATAL: gh_rm_get_vmid is not GPL-exported by this Samsung/GKI tree' >&2; exit 1;
}
grep -qF 'qcom_scm_assign_mem' "$QCOM_SCM_HEADER" || {
  echo 'FATAL: qcom_scm_assign_mem declaration is unavailable' >&2; exit 1;
}

python3 - "$QCOM_SRC" "$GUNYAH_MAKEFILE" "$MODULES_BZL" "$BACKING_SRC" "$QCOM_SCM_HEADER" <<'PY'
from pathlib import Path
import re
import sys

qcom_path, gunyah_mk_path, modules_bzl_path, backing_path, scm_header_path = map(Path, sys.argv[1:])
qcom = qcom_path.read_text()
gunyah_mk = gunyah_mk_path.read_text()
modules_bzl = modules_bzl_path.read_text()
backing = backing_path.read_text()
scm_header = scm_header_path.read_text()

def span(text: str, signature: str):
    start = text.find(signature)
    if start < 0:
        raise SystemExit(f"FATAL: cannot locate {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit(f"FATAL: no opening brace for {signature}")
    depth = 0
    for pos in range(brace, len(text)):
        if text[pos] == "{":
            depth += 1
        elif text[pos] == "}":
            depth -= 1
            if depth == 0:
                return start, pos + 1
    raise SystemExit(f"FATAL: unterminated {signature}")

def patch_function(text: str, signature: str, transform):
    start, end = span(text, signature)
    old = text[start:end]
    new = transform(old)
    if new == old:
        raise SystemExit(f"FATAL: no changes while patching {signature}")
    return text[:start] + new + text[end:]

# Apply the SM8650 SCM/RM VMID fix without debug-only printk imports.
if "static u16 qcom_scm_map_vmid(u16 vmid)" not in qcom:
    pat = re.compile(r'(?m)^(#define QCOM_SCM_MAX_MANAGED_VMID\s+0x3F\s*)$')
    m = pat.search(qcom)
    if not m:
        raise SystemExit("FATAL: Qualcomm VMID define anchor missing")
    helper = (
        m.group(1)
        + "\n\nstatic u16 qcom_scm_map_vmid(u16 vmid)\n"
        + "{\n"
        + "\tif (vmid <= QCOM_SCM_MAX_MANAGED_VMID)\n"
        + "\t\treturn vmid;\n\n"
        + "\treturn QCOM_SCM_RM_MANAGED_VMID;\n"
        + "}\n"
    )
    qcom = qcom[:m.start()] + helper + qcom[m.end():]

if "gh_rm_get_vmid(rm, &self_vmid)" not in qcom:
    def pre(block: str):
        block, n = re.subn(
            r'\tint ret = 0, i, n;\n\tu16 vmid;\n',
            '\tint ret = 0, i, n;\n\tu16 self_vmid, vmid;\n\n'
            '\tret = gh_rm_get_vmid(rm, &self_vmid);\n'
            '\tif (ret)\n'
            '\t\treturn ret;\n',
            block,
            count=1,
        )
        if n != 1:
            raise SystemExit("FATAL: pre_mem_share declarations changed")
        block, n = re.subn(
            r'\t\tif \(vmid <= QCOM_SCM_MAX_MANAGED_VMID\)\n'
            r'\t\t\tnew_perms\[n\]\.vmid = vmid;\n'
            r'\t\telse\n'
            r'\t\t\tnew_perms\[n\]\.vmid = QCOM_SCM_RM_MANAGED_VMID;\n',
            '\t\tnew_perms[n].vmid = qcom_scm_map_vmid(vmid);\n',
            block,
            count=1,
        )
        if n != 1:
            raise SystemExit("FATAL: pre_mem_share ACL mapping changed")
        fixed = '\tsrc = BIT_ULL(QCOM_SCM_VMID_HLOS);\n'
        if block.count(fixed) != 1:
            raise SystemExit("FATAL: fixed HLOS source VMID anchor missing")
        block = block.replace(
            fixed,
            '\tsrc = BIT_ULL(qcom_scm_map_vmid(self_vmid));\n',
            1,
        )
        block, n = re.subn(
            r'\t\tif \(vmid <= QCOM_SCM_MAX_MANAGED_VMID\)\n'
            r'\t\t\tsrc \|= BIT_ULL\(vmid\);\n'
            r'\t\telse\n'
            r'\t\t\tsrc \|= BIT_ULL\(QCOM_SCM_RM_MANAGED_VMID\);\n',
            '\t\tsrc |= BIT_ULL(qcom_scm_map_vmid(vmid));\n',
            block,
            count=1,
        )
        if n != 1:
            raise SystemExit("FATAL: pre_mem_share rollback mapping changed")
        return block

    qcom = patch_function(qcom, "static int qcom_scm_gh_rm_pre_mem_share(", pre)

    def post(block: str):
        block, n = re.subn(
            r'\tint ret = 0, i, n;\n\tu16 vmid;\n',
            '\tint ret = 0, i, n;\n\tu16 self_vmid, vmid;\n\n'
            '\tret = gh_rm_get_vmid(rm, &self_vmid);\n'
            '\tif (ret)\n'
            '\t\treturn ret;\n',
            block,
            count=1,
        )
        if n != 1:
            raise SystemExit("FATAL: post_mem_reclaim declarations changed")
        block, n = re.subn(
            r'\t\tif \(vmid <= QCOM_SCM_MAX_MANAGED_VMID\)\n'
            r'\t\t\tsrc \|= \(1ull << vmid\);\n'
            r'\t\telse\n'
            r'\t\t\tsrc \|= \(1ull << QCOM_SCM_RM_MANAGED_VMID\);\n',
            '\t\tsrc |= BIT_ULL(qcom_scm_map_vmid(vmid));\n',
            block,
            count=1,
        )
        if n != 1:
            raise SystemExit("FATAL: post_mem_reclaim VMID mapping changed")
        return block

    qcom = patch_function(qcom, "static int qcom_scm_gh_rm_post_mem_reclaim(", post)

# The real S24 Ultra kernel keeps CONFIG_QCOM_SCM=n and
# CONFIG_GUNYAH_QCOM_PLATFORM=n because both drivers come from vendor_boot.
# For this CI-only replacement module, expose the real SCM prototype only while
# compiling gunyah_qcom.o. No final kernel config symbol is changed.
scm_guard = "#if IS_ENABLED(CONFIG_QCOM_SCM)"
scm_guard_test = "#if IS_ENABLED(CONFIG_QCOM_SCM) || defined(E3Q_GUNYAH_VENDOR_SCM_API)"
if scm_guard_test not in scm_header:
    count = scm_header.count(scm_guard)
    if count != 1:
        raise SystemExit(f"FATAL: expected one CONFIG_QCOM_SCM API guard, found {count}")
    scm_header = scm_header.replace(scm_guard, scm_guard_test, 1)

gunyah_forced = "obj-m += gunyah_qcom.o # e3q vendor_boot live-test module; not packaged by AnyKernel"
if gunyah_forced not in gunyah_mk:
    pat = re.compile(r'(?m)^obj-\$\(CONFIG_GUNYAH_QCOM_PLATFORM\)\s*\+=\s*gunyah_qcom\.o\s*$')
    gunyah_mk, n = pat.subn(gunyah_forced, gunyah_mk, count=1)
    if n != 1:
        raise SystemExit("FATAL: gunyah_qcom Makefile target changed")

scm_cflag = "CFLAGS_gunyah_qcom.o += -DE3Q_GUNYAH_VENDOR_SCM_API"
if scm_cflag not in gunyah_mk:
    anchor = gunyah_forced + "\n"
    if gunyah_mk.count(anchor) != 1:
        raise SystemExit("FATAL: gunyah_qcom build-only target anchor is ambiguous")
    gunyah_mk = gunyah_mk.replace(anchor, anchor + scm_cflag + "\n", 1)

# Kleaf rejects produced modules not declared in module_implicit_outs.
needed = {"drivers/virt/gunyah/gunyah_qcom.ko"}
start = modules_bzl.find("_ARM64_GKI_MODULES_LIST = [")
if start < 0:
    raise SystemExit("FATAL: ARM64 GKI module list missing")
end = modules_bzl.find("\n]", start)
if end < 0:
    raise SystemExit("FATAL: ARM64 GKI module list terminator missing")
block = modules_bzl[start:end]
marker = "# keep sorted\n"
marker_pos = block.find(marker)
if marker_pos < 0:
    raise SystemExit("FATAL: ARM64 GKI sorted marker missing")
existing = set(re.findall(r'^\s*"([^"]+\.ko)",\s*$', block, re.MULTILINE))
if not needed.issubset(existing):
    wanted = sorted(existing | needed)
    content_start = start + marker_pos + len(marker)
    modules_bzl = (
        modules_bzl[:content_start]
        + ''.join(f'    "{x}",\n' for x in wanted)
        + modules_bzl[end:]
    )

# Drop only our alloc_contig_pages ownership ref; GUP refs may still exist here.
if "__free_page(nth_page(chunk->base, i));" not in backing:
    old = re.compile(
        r'static void gh_extent_free_one\(struct gh_extent_chunk \*chunk\)\n\{\n'
        r'\tunsigned long nr_pages;\n\n'
        r'\tif \(!chunk \|\| !chunk->base\)\n\t\treturn;\n\n'
        r'\tnr_pages = 1UL << chunk->order;\n'
        r'\tif \(chunk->contig\)\n\t\tfree_contig_range\(page_to_pfn\(chunk->base\), nr_pages\);\n'
        r'\telse\n\t\t__free_pages\(chunk->base, chunk->order\);\n\n'
        r'\tchunk->base = NULL;\n\}\n'
    )
    new = (
        'static void gh_extent_free_one(struct gh_extent_chunk *chunk)\n{\n'
        '\tunsigned long nr_pages;\n'
        '\tunsigned long i;\n\n'
        '\tif (!chunk || !chunk->base)\n'
        '\t\treturn;\n\n'
        '\tnr_pages = 1UL << chunk->order;\n'
        '\tif (chunk->contig) {\n'
        '\t\tfor (i = 0; i < nr_pages; i++)\n'
        '\t\t\t__free_page(nth_page(chunk->base, i));\n'
        '\t} else {\n'
        '\t\t__free_pages(chunk->base, chunk->order);\n'
        '\t}\n\n'
        '\tchunk->base = NULL;\n'
        '}\n'
    )
    backing, n = old.subn(new, backing, count=1)
    if n != 1:
        raise SystemExit("FATAL: bounded-backing teardown layout changed")

qcom_path.write_text(qcom)
gunyah_mk_path.write_text(gunyah_mk)
modules_bzl_path.write_text(modules_bzl)
backing_path.write_text(backing)
scm_header_path.write_text(scm_header)
PY

# Fail closed on runtime semantics, vendor SCM import mode, build packaging and cleanup.
grep -qF 'static u16 qcom_scm_map_vmid(u16 vmid)' "$QCOM_SRC"
grep -qF 'gh_rm_get_vmid(rm, &self_vmid)' "$QCOM_SRC"
grep -qF 'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' "$QCOM_SRC"
grep -qF 'new_perms[n].vmid = qcom_scm_map_vmid(vmid);' "$QCOM_SRC"
grep -qF 'src |= BIT_ULL(qcom_scm_map_vmid(vmid));' "$QCOM_SRC"
! grep -qF 'GH_QCOM_SCM' "$QCOM_SRC"
grep -qF 'obj-m += gunyah_qcom.o # e3q vendor_boot live-test module; not packaged by AnyKernel' "$GUNYAH_MAKEFILE"
grep -qF 'CFLAGS_gunyah_qcom.o += -DE3Q_GUNYAH_VENDOR_SCM_API' "$GUNYAH_MAKEFILE"
grep -qF '#if IS_ENABLED(CONFIG_QCOM_SCM) || defined(E3Q_GUNYAH_VENDOR_SCM_API)' "$QCOM_SCM_HEADER"
grep -qF '"drivers/virt/gunyah/gunyah_qcom.ko",' "$MODULES_BZL"
grep -qF '__free_page(nth_page(chunk->base, i));' "$BACKING_SRC"
! grep -qF 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$BACKING_SRC"
grep -qF 'mapping->parcel.n_mem_entries > 8192' "$GUNYAH_DIR/vm_mgr.c"
grep -qF 'ret = -E2BIG;' "$GUNYAH_DIR/vm_mgr.c"
grep -qF 'EXPORT_SYMBOL_GPL(gh_rm_get_vmid);' "$RM_RPC"
grep -qF 'qcom_scm_assign_mem' "$QCOM_SCM_HEADER"

echo 'e3q Gunyah follow-up applied: SCM RM-VMID mapping + vendor-SCM test-module import + safe contig teardown'
