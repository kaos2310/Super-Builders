#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-vm-metadata-allocation.sh <kernel-tree>}"
VM_TARGET="$KERNEL_TREE/drivers/virt/gunyah/vm_mgr.c"
RPC_TARGET="$KERNEL_TREE/drivers/virt/gunyah/rsc_mgr_rpc.c"

# Keep the exact, already device-tested e3q Gunyah compatibility transform as
# the immutable base. This branch layers only diagnostic/safety changes below;
# the grouped IRQFD fix, kvcalloc metadata fix, and existing GH_DIAG markers
# remain sourced from the last known-good kernel branch.
BASE_COMMIT="def60b7761847bc19c69b4be983699db2fe53f3a"
BASE_URL="https://raw.githubusercontent.com/kaos2310/Super-Builders/${BASE_COMMIT}/android14-6.1/build-helpers/apply-e3q-gunyah-vm-metadata-allocation.sh"
BASE_HELPER="$(mktemp -t e3q-gunyah-base.XXXXXX.sh)"
trap 'rm -f "$BASE_HELPER"' EXIT

curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
  "$BASE_URL" -o "$BASE_HELPER"

grep -qF 'GH_DIAG mem_alloc enter' "$BASE_HELPER"
grep -qF 'GH_DIAG mem_share begin' "$BASE_HELPER"
grep -qF 'struct gh_irqfd_group {' "$BASE_HELPER"
grep -qF 'using edge-compatible semantics' "$BASE_HELPER"

bash "$BASE_HELPER" "$KERNEL_TREE"

test -f "$VM_TARGET" || {
  echo "FATAL: Gunyah VM manager not found after base patch: $VM_TARGET" >&2
  exit 1
}
test -f "$RPC_TARGET" || {
  echo "FATAL: Gunyah RM RPC source not found after base patch: $RPC_TARGET" >&2
  exit 1
}

# Refuse only pathological parcels. 8192 extents still permits the RM APPEND
# path to be exercised and diagnosed, while the observed 34213-extent parcel
# is rejected before it can enter the platform-resetting RM transaction.
python3 - "$VM_TARGET" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()

limit = 8192
refuse_marker = "GH_DIAG mem_share refused"
begin_marker = "GH_DIAG mem_share begin"

# Upgrade an older 512-entry diagnostic guard in-place if present.
source = source.replace(
    "mapping->parcel.n_mem_entries > 512",
    f"mapping->parcel.n_mem_entries > {limit}",
)
source = source.replace(
    "mapping->parcel.n_mem_entries, 512U);",
    f"mapping->parcel.n_mem_entries, {limit}U);",
)

if refuse_marker not in source:
    old = (
        '\t\tpr_info("GH_DIAG mem_share begin vmid=%u label=%u type=%u entries=%zu\\n",\n'
        '\t\t\tghvm->vmid, mapping->parcel.label,\n'
        '\t\t\t(unsigned int)mapping->share_type,\n'
        '\t\t\tmapping->parcel.n_mem_entries);\n'
    )
    new = (
        f'\t\tif (mapping->parcel.n_mem_entries > {limit}) {{\n'
        '\t\t\tpr_err("GH_DIAG mem_share refused vmid=%u label=%u type=%u entries=%zu limit=%u\\n",\n'
        '\t\t\t\tghvm->vmid, mapping->parcel.label,\n'
        '\t\t\t\t(unsigned int)mapping->share_type,\n'
        f'\t\t\t\tmapping->parcel.n_mem_entries, {limit}U);\n'
        '\t\t\tret = -E2BIG;\n'
        '\t\t\tgoto err;\n'
        '\t\t}\n\n'
        + old
    )
    if source.count(old) != 1:
        raise SystemExit(
            "FATAL: cannot place e3q Gunyah mem-share guard; "
            f"expected one GH_DIAG share marker, found {source.count(old)}"
        )
    source = source.replace(old, new, 1)

checks = {
    "single guard log": source.count(refuse_marker) == 1,
    "single existing begin log": source.count(begin_marker) == 1,
    "entry threshold": f"mapping->parcel.n_mem_entries > {limit}" in source,
    "bounded failure": "ret = -E2BIG;" in source,
    "guard precedes RM share diagnostics": source.index(refuse_marker) < source.index(begin_marker),
    "legacy 512 threshold removed": "mapping->parcel.n_mem_entries > 512" not in source,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("FATAL: incomplete Gunyah mem-share guard: " + ", ".join(failed))

path.write_text(source)
print(
    f"Applied e3q Gunyah mem-share safety guard to {path}: "
    f"refuse parcels with more than {limit} physical extents"
)
PY

# Instrument the Resource Manager RPC path so pstore shows whether a reset
# occurs in the initial MEM_SHARE/LEND transaction or in a specific MEM_APPEND
# batch. The transform is deliberately strict: source drift aborts the build.
python3 - "$RPC_TARGET" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()

if "GH_DIAG rm_mem_share call begin" not in source:
    # Make response-size diagnostics well-defined even if the RM call fails.
    old = "size_t msg_size = 0, initial_mem_entries = p->n_mem_entries, resp_size;"
    new = "size_t msg_size = 0, initial_mem_entries = p->n_mem_entries, resp_size = 0;"
    if source.count(old) != 1:
        raise SystemExit(
            "FATAL: cannot initialize Gunyah RM response size; "
            f"expected one declaration, found {source.count(old)}"
        )
    source = source.replace(old, new, 1)

    # Log the exact initial MEM_SHARE/MEM_LEND call boundary.
    old = (
        "\tret = gh_rm_call(rm, message_id, msg, msg_size, (void **)&resp, &resp_size);\n"
        "\tkfree(msg);\n"
    )
    new = (
        '\tpr_info("GH_DIAG rm_mem_share call begin rpc=%#x label=%u total=%zu initial=%zu append=%u msg_size=%zu\\n",\n'
        "\t\tmessage_id, p->label, p->n_mem_entries, initial_mem_entries,\n"
        "\t\t(unsigned int)(initial_mem_entries != p->n_mem_entries), msg_size);\n"
        "\tret = gh_rm_call(rm, message_id, msg, msg_size, (void **)&resp, &resp_size);\n"
        '\tpr_info("GH_DIAG rm_mem_share call end rpc=%#x label=%u ret=%d resp_size=%zu\\n",\n'
        "\t\tmessage_id, p->label, ret, resp_size);\n"
        "\tkfree(msg);\n"
    )
    if source.count(old) != 1:
        raise SystemExit(
            "FATAL: cannot instrument initial Gunyah RM mem-share call; "
            f"found {source.count(old)} candidates"
        )
    source = source.replace(old, new, 1)

    old = (
        "\tp->mem_handle = le32_to_cpu(*resp);\n"
        "\tkfree(resp);\n"
    )
    new = (
        "\tp->mem_handle = le32_to_cpu(*resp);\n"
        '\tpr_info("GH_DIAG rm_mem_share handle rpc=%#x label=%u handle=%u\\n",\n'
        "\t\tmessage_id, p->label, p->mem_handle);\n"
        "\tkfree(resp);\n"
    )
    if source.count(old) != 1:
        raise SystemExit(
            "FATAL: cannot instrument Gunyah RM mem-handle response; "
            f"found {source.count(old)} candidates"
        )
    source = source.replace(old, new, 1)

    # Add a batch counter around the existing 512-entry APPEND loop.
    old = (
        "\tbool end_append;\n"
        "\tint ret = 0;\n"
        "\tsize_t n;\n"
    )
    new = (
        "\tbool end_append;\n"
        "\tint ret = 0;\n"
        "\tsize_t n, batch = 0, total_entries = n_mem_entries;\n"
    )
    if source.count(old) != 1:
        raise SystemExit(
            "FATAL: cannot instrument Gunyah RM append loop declarations; "
            f"found {source.count(old)} candidates"
        )
    source = source.replace(old, new, 1)

    old = (
        "\t\tret = _gh_rm_mem_append(rm, mem_handle, end_append, mem_entries, n);\n"
        "\t\tif (ret)\n"
        "\t\t\tbreak;\n\n"
        "\t\tmem_entries += n;\n"
        "\t\tn_mem_entries -= n;\n"
    )
    new = (
        '\t\tpr_info("GH_DIAG rm_append batch begin handle=%u batch=%zu entries=%zu remaining=%zu total=%zu end=%u\\n",\n'
        "\t\t\tmem_handle, batch, n, n_mem_entries, total_entries,\n"
        "\t\t\t(unsigned int)end_append);\n"
        "\t\tret = _gh_rm_mem_append(rm, mem_handle, end_append, mem_entries, n);\n"
        '\t\tpr_info("GH_DIAG rm_append batch end handle=%u batch=%zu ret=%d\\n",\n'
        "\t\t\tmem_handle, batch, ret);\n"
        "\t\tif (ret)\n"
        "\t\t\tbreak;\n\n"
        "\t\tmem_entries += n;\n"
        "\t\tn_mem_entries -= n;\n"
        "\t\tbatch++;\n"
    )
    if source.count(old) != 1:
        raise SystemExit(
            "FATAL: cannot instrument Gunyah RM append loop body; "
            f"found {source.count(old)} candidates"
        )
    source = source.replace(old, new, 1)

    # Put call-level markers around every individual MEM_APPEND RPC.
    old = (
        "\tret = gh_rm_call(rm, GH_RM_RPC_MEM_APPEND, msg, msg_size, NULL, NULL);\n"
        "\tkfree(msg);\n"
    )
    new = (
        '\tpr_info("GH_DIAG rm_append call begin handle=%u entries=%zu end=%u msg_size=%zu\\n",\n'
        "\t\tmem_handle, n_mem_entries, (unsigned int)end_append, msg_size);\n"
        "\tret = gh_rm_call(rm, GH_RM_RPC_MEM_APPEND, msg, msg_size, NULL, NULL);\n"
        '\tpr_info("GH_DIAG rm_append call end handle=%u entries=%zu end=%u ret=%d\\n",\n'
        "\t\tmem_handle, n_mem_entries, (unsigned int)end_append, ret);\n"
        "\tkfree(msg);\n"
    )
    if source.count(old) != 1:
        raise SystemExit(
            "FATAL: cannot instrument Gunyah RM append RPC; "
            f"found {source.count(old)} candidates"
        )
    source = source.replace(old, new, 1)

    # Make the transition from the initial share to the remaining APPENDs explicit.
    old = (
        "\tif (initial_mem_entries != p->n_mem_entries) {\n"
        "\t\tret = gh_rm_mem_append(rm, p->mem_handle,\n"
        "\t\t\t\t       &p->mem_entries[initial_mem_entries],\n"
        "\t\t\t\t       p->n_mem_entries - initial_mem_entries);\n"
        "\t\tif (ret) {\n"
    )
    new = (
        "\tif (initial_mem_entries != p->n_mem_entries) {\n"
        '\t\tpr_info("GH_DIAG rm_append sequence begin handle=%u remaining=%zu total=%zu\\n",\n'
        "\t\t\tp->mem_handle, p->n_mem_entries - initial_mem_entries,\n"
        "\t\t\tp->n_mem_entries);\n"
        "\t\tret = gh_rm_mem_append(rm, p->mem_handle,\n"
        "\t\t\t\t       &p->mem_entries[initial_mem_entries],\n"
        "\t\t\t\t       p->n_mem_entries - initial_mem_entries);\n"
        '\t\tpr_info("GH_DIAG rm_append sequence end handle=%u ret=%d\\n",\n'
        "\t\t\tp->mem_handle, ret);\n"
        "\t\tif (ret) {\n"
    )
    if source.count(old) != 1:
        raise SystemExit(
            "FATAL: cannot instrument Gunyah RM append sequence; "
            f"found {source.count(old)} candidates"
        )
    source = source.replace(old, new, 1)

checks = {
    "initial call begin": source.count("GH_DIAG rm_mem_share call begin") == 1,
    "initial call end": source.count("GH_DIAG rm_mem_share call end") == 1,
    "mem handle": source.count("GH_DIAG rm_mem_share handle") == 1,
    "append sequence begin": source.count("GH_DIAG rm_append sequence begin") == 1,
    "append sequence end": source.count("GH_DIAG rm_append sequence end") == 1,
    "append batch begin": source.count("GH_DIAG rm_append batch begin") == 1,
    "append batch end": source.count("GH_DIAG rm_append batch end") == 1,
    "append call begin": source.count("GH_DIAG rm_append call begin") == 1,
    "append call end": source.count("GH_DIAG rm_append call end") == 1,
    "upstream batch size retained": "#define GH_RM_MAX_MEM_ENTRIES 512" in source,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("FATAL: incomplete Gunyah RM diagnostics: " + ", ".join(failed))

path.write_text(source)
print(f"Applied Gunyah RM MEM_SHARE/MEM_APPEND diagnostics to {path}")
PY

grep -qF 'GH_DIAG mem_share refused' "$VM_TARGET"
grep -qF 'mapping->parcel.n_mem_entries > 8192' "$VM_TARGET"
grep -qF 'ret = -E2BIG;' "$VM_TARGET"
grep -qF 'GH_DIAG mem_share begin' "$VM_TARGET"

grep -qF 'GH_DIAG rm_mem_share call begin' "$RPC_TARGET"
grep -qF 'GH_DIAG rm_mem_share call end' "$RPC_TARGET"
grep -qF 'GH_DIAG rm_append sequence begin' "$RPC_TARGET"
grep -qF 'GH_DIAG rm_append batch begin' "$RPC_TARGET"
grep -qF 'GH_DIAG rm_append call begin' "$RPC_TARGET"
grep -qF '#define GH_RM_MAX_MEM_ENTRIES 512' "$RPC_TARGET"

echo 'e3q Gunyah diagnostics verified: guard=8192 extents, RM batch=512 entries, failure=-E2BIG'
