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
RM_RPC="$GUNYAH_DIR/rsc_mgr_rpc.c"
VM_TARGET="$GUNYAH_DIR/vm_mgr.c"
QCOM_SCM_HEADER="$KERNEL_TREE/include/linux/qcom_scm.h"

for f in "$QCOM_SRC" "$GUNYAH_MAKEFILE" "$FIRMWARE_MAKEFILE" "$MODULES_BZL" \
         "$BACKING_SRC" "$RM_HEADER" "$RM_RPC" "$VM_TARGET" "$QCOM_SCM_HEADER"; do
  test -f "$f" || { echo "FATAL: required e3q Gunyah source missing: $f" >&2; exit 1; }
done

grep -qF 'gh_rm_get_vmid' "$RM_HEADER" || {
  echo 'FATAL: gh_rm_get_vmid declaration is unavailable' >&2; exit 1;
}
grep -qF 'EXPORT_SYMBOL_GPL(gh_rm_get_vmid);' "$RM_RPC" || {
  echo 'FATAL: gh_rm_get_vmid is not GPL-exported by this Samsung/GKI tree' >&2; exit 1;
}
grep -qF 'extern int qcom_scm_assign_mem(' "$QCOM_SCM_HEADER" || {
  echo 'FATAL: qcom_scm_assign_mem extern declaration is unavailable' >&2; exit 1;
}
grep -Eq '^qcom-scm-objs[[:space:]]*\+=[[:space:]]*qcom_scm\.o[[:space:]]+qcom_scm-smc\.o[[:space:]]+qcom_scm-legacy\.o' "$FIRMWARE_MAKEFILE" || {
  echo 'FATAL: unexpected qcom-scm composite target layout' >&2; exit 1;
}

python3 - "$QCOM_SRC" "$GUNYAH_MAKEFILE" "$FIRMWARE_MAKEFILE" "$MODULES_BZL" "$BACKING_SRC" <<'PY'
from pathlib import Path
import re
import sys

qcom_path, gunyah_mk_path, firmware_mk_path, modules_bzl_path, backing_path = map(Path, sys.argv[1:])
qcom = qcom_path.read_text()
gunyah_mk = gunyah_mk_path.read_text()
firmware_mk = firmware_mk_path.read_text()
modules_bzl = modules_bzl_path.read_text()
backing = backing_path.read_text()


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


# SM8650 fix: SCM accepts only managed VMIDs <= 0x3f. RM-created VMIDs are
# mapped to the reserved RM-managed SCM VMID 0x3a for share/reclaim operations.
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

# Build the two Samsung vendor_boot modules only as CI outputs. The final GKI
# config remains unchanged and AnyKernel still packages only Image. Building
# qcom-scm.ko in the same Kbuild graph gives modpost the real
# qcom_scm_assign_mem provider/CRC instead of relying on a synthetic symvers.
gunyah_forced = "obj-m += gunyah_qcom.o # e3q vendor_boot live-test module; not packaged by AnyKernel"
if gunyah_forced not in gunyah_mk:
    pat = re.compile(r'(?m)^obj-\$\(CONFIG_GUNYAH_QCOM_PLATFORM\)\s*\+=\s*gunyah_qcom\.o\s*$')
    gunyah_mk, n = pat.subn(gunyah_forced, gunyah_mk, count=1)
    if n != 1:
        raise SystemExit("FATAL: gunyah_qcom Makefile target changed")

scm_forced = "obj-m += qcom-scm.o # e3q vendor_boot build-only provider; not packaged by AnyKernel"
if scm_forced not in firmware_mk:
    pat = re.compile(r'(?m)^obj-\$\(CONFIG_QCOM_SCM\)\s*\+=\s*qcom-scm\.o\s*$')
    firmware_mk, n = pat.subn(scm_forced, firmware_mk, count=1)
    if n != 1:
        raise SystemExit("FATAL: qcom-scm Makefile target changed")

# Kleaf rejects produced modules not declared in module_implicit_outs.
needed = {"drivers/firmware/qcom-scm.ko", "drivers/virt/gunyah/gunyah_qcom.ko"}
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

# Drop only our alloc_contig_pages ownership ref. The Gunyah GUP references can
# still be alive while the anonymous backing FD is released asynchronously.
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
firmware_mk_path.write_text(firmware_mk)
modules_bzl_path.write_text(modules_bzl)
backing_path.write_text(backing)
PY

# Fail closed on runtime semantics, provider availability, build packaging and cleanup.
require_fixed() {
  local needle="$1" file="$2" label="$3"
  grep -qF "$needle" "$file" || {
    echo "FATAL: missing ${label}: ${needle} in ${file}" >&2
    exit 1
  }
}

require_regex() {
  local regex="$1" file="$2" label="$3"
  grep -Eq "$regex" "$file" || {
    echo "FATAL: missing ${label}: ${regex} in ${file}" >&2
    exit 1
  }
}

require_absent() {
  local needle="$1" file="$2" label="$3"
  if grep -qF "$needle" "$file"; then
    echo "FATAL: unexpected ${label}: ${needle} in ${file}" >&2
    exit 1
  fi
}

require_fixed 'static u16 qcom_scm_map_vmid(u16 vmid)' "$QCOM_SRC" 'SCM VMID mapping helper'
require_fixed 'gh_rm_get_vmid(rm, &self_vmid)' "$QCOM_SRC" 'dynamic RM self-VMID lookup'
require_fixed 'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' "$QCOM_SRC" 'SCM source VMID mapping'
require_fixed 'new_perms[n].vmid = qcom_scm_map_vmid(vmid);' "$QCOM_SRC" 'SCM destination VMID mapping'
require_fixed 'src |= BIT_ULL(qcom_scm_map_vmid(vmid));' "$QCOM_SRC" 'SCM reclaim VMID mapping'
require_absent 'GH_QCOM_SCM' "$QCOM_SRC" 'abandoned GH_QCOM_SCM workaround'

require_fixed 'obj-m += gunyah_qcom.o # e3q vendor_boot live-test module; not packaged by AnyKernel' "$GUNYAH_MAKEFILE" 'gunyah_qcom CI module target'
require_fixed 'obj-m += qcom-scm.o # e3q vendor_boot build-only provider; not packaged by AnyKernel' "$FIRMWARE_MAKEFILE" 'qcom-scm CI provider target'
require_regex '^qcom-scm-objs[[:space:]]*\+=[[:space:]]*qcom_scm\.o[[:space:]]+qcom_scm-smc\.o[[:space:]]+qcom_scm-legacy\.o' "$FIRMWARE_MAKEFILE" 'qcom-scm composite target'
require_fixed '"drivers/firmware/qcom-scm.ko",' "$MODULES_BZL" 'qcom-scm Kleaf implicit output'
require_fixed '"drivers/virt/gunyah/gunyah_qcom.ko",' "$MODULES_BZL" 'gunyah_qcom Kleaf implicit output'

require_fixed '__free_page(nth_page(chunk->base, i));' "$BACKING_SRC" 'safe contiguous backing teardown'
require_absent 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$BACKING_SRC" 'unsafe contiguous teardown'

# The S24 runtime trace proved the old total-parcel guard itself is the blocker.
# It must stay absent here; large parcels are intentionally delegated to RM's
# existing 512-entry MEM_APPEND batching protocol.
require_absent 'mapping->parcel.n_mem_entries > 8192' "$VM_TARGET" 'synthetic 8192 total-entry guard'
require_absent 'GH_DIAG mem_share refused' "$VM_TARGET" 'synthetic mem-share refusal path'
require_fixed 'GH_DIAG mem_share begin' "$VM_TARGET" 'VM memory-share diagnostics'
require_fixed 'GH_DIAG mem_share end' "$VM_TARGET" 'VM memory-share completion diagnostics'
require_fixed 'GH_RM_RPC_MEM_APPEND' "$RM_RPC" 'RM MEM_APPEND opcode'
require_fixed 'static int gh_rm_mem_append(' "$RM_RPC" 'RM append batching helper'
require_fixed 'static int _gh_rm_mem_append(' "$RM_RPC" 'RM append RPC helper'
require_fixed 'GH_DIAG rm_mem_share call begin' "$RM_RPC" 'RM initial share diagnostics'
require_fixed 'GH_DIAG rm_append sequence begin' "$RM_RPC" 'RM append-sequence diagnostics'
require_fixed 'GH_DIAG rm_append batch begin' "$RM_RPC" 'RM append-batch diagnostics'
require_fixed 'EXPORT_SYMBOL_GPL(gh_rm_get_vmid);' "$RM_RPC" 'gh_rm_get_vmid export'
require_fixed 'extern int qcom_scm_assign_mem(' "$QCOM_SCM_HEADER" 'qcom_scm_assign_mem declaration'

echo 'e3q Gunyah follow-up applied: RM MEM_APPEND large-parcel path + SCM RM-VMID mapping + qcom-scm CI provider + safe contig teardown'
