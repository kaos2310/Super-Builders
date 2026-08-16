#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-vm-metadata-allocation.sh <kernel-tree>}"
VM_TARGET="$KERNEL_TREE/drivers/virt/gunyah/vm_mgr.c"
RPC_TARGET="$KERNEL_TREE/drivers/virt/gunyah/rsc_mgr_rpc.c"

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

python3 - "$VM_TARGET" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
source = path.read_text()
limit = 8192

source = source.replace(
    "mapping->parcel.n_mem_entries > 512",
    f"mapping->parcel.n_mem_entries > {limit}",
)
source = source.replace(
    "mapping->parcel.n_mem_entries, 512U);",
    f"mapping->parcel.n_mem_entries, {limit}U);",
)

if "GH_DIAG mem_share refused" not in source:
    pattern = re.compile(
        r'(?P<indent>^[ \t]*)pr_info\("GH_DIAG mem_share begin vmid=%u label=%u type=%u entries=%zu\\n",\n'
        r'(?P=indent)[ \t]+ghvm->vmid, mapping->parcel\.label,\n'
        r'(?P=indent)[ \t]+\(unsigned int\)mapping->share_type,\n'
        r'(?P=indent)[ \t]+mapping->parcel\.n_mem_entries\);\n',
        re.MULTILINE,
    )
    match = pattern.search(source)
    if not match:
        raise SystemExit("FATAL: cannot locate GH_DIAG mem_share begin marker for safety guard")
    indent = match.group("indent")
    guard = (
        f"{indent}if (mapping->parcel.n_mem_entries > {limit}) {{\n"
        f'{indent}\tpr_err("GH_DIAG mem_share refused vmid=%u label=%u type=%u entries=%zu limit=%u\\n",\n'
        f"{indent}\t\tghvm->vmid, mapping->parcel.label,\n"
        f"{indent}\t\t(unsigned int)mapping->share_type,\n"
        f"{indent}\t\tmapping->parcel.n_mem_entries, {limit}U);\n"
        f"{indent}\tret = -E2BIG;\n"
        f"{indent}\tgoto err;\n"
        f"{indent}}}\n\n"
    )
    source = source[:match.start()] + guard + source[match.start():]

checks = {
    "single guard log": source.count("GH_DIAG mem_share refused") == 1,
    "single begin log": source.count("GH_DIAG mem_share begin") == 1,
    "entry threshold": f"mapping->parcel.n_mem_entries > {limit}" in source,
    "bounded failure": "ret = -E2BIG;" in source,
    "guard precedes share": source.index("GH_DIAG mem_share refused") < source.index("GH_DIAG mem_share begin"),
    "legacy 512 guard removed": "mapping->parcel.n_mem_entries > 512" not in source,
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

python3 - "$RPC_TARGET" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
source = path.read_text()

def replace_once(pattern, repl, description, flags=re.MULTILINE):
    global source
    rx = re.compile(pattern, flags)
    matches = list(rx.finditer(source))
    if len(matches) != 1:
        raise SystemExit(f"FATAL: cannot instrument {description}; found {len(matches)} candidates")
    match = matches[0]
    rendered = repl
    for name, value in match.groupdict().items():
        if value is not None:
            rendered = rendered.replace("{" + name + "}", value)
    source = source[:match.start()] + rendered + source[match.end():]

if "GH_DIAG rm_mem_share call begin" not in source:
    replace_once(
        r'(?P<i>^[ \t]*)size_t msg_size = 0, initial_mem_entries = p->n_mem_entries, resp_size;',
        r'{i}size_t msg_size = 0, initial_mem_entries = p->n_mem_entries, resp_size = 0;',
        "Gunyah RM response-size declaration",
    )

    replace_once(
        r'(?P<i>^[ \t]*)ret = gh_rm_call\(rm, message_id, msg, msg_size, \(void \*\*\)&resp, &resp_size\);\n'
        r'(?P=i)kfree\(msg\);',
        r'''{i}pr_info("GH_DIAG rm_mem_share call begin rpc=%#x label=%u total=%zu initial=%zu append=%u msg_size=%zu\n",
{i}\tmessage_id, p->label, p->n_mem_entries, initial_mem_entries,
{i}\t(unsigned int)(initial_mem_entries != p->n_mem_entries), msg_size);
{i}ret = gh_rm_call(rm, message_id, msg, msg_size, (void **)&resp, &resp_size);
{i}pr_info("GH_DIAG rm_mem_share call end rpc=%#x label=%u ret=%d resp_size=%zu\n",
{i}\tmessage_id, p->label, ret, resp_size);
{i}kfree(msg);''',
        "initial Gunyah RM MEM_SHARE/MEM_LEND call",
    )

    replace_once(
        r'(?P<i>^[ \t]*)p->mem_handle = le32_to_cpu\(\*resp\);\n'
        r'(?P=i)kfree\(resp\);',
        r'''{i}p->mem_handle = le32_to_cpu(*resp);
{i}pr_info("GH_DIAG rm_mem_share handle rpc=%#x label=%u handle=%u\n",
{i}\tmessage_id, p->label, p->mem_handle);
{i}kfree(resp);''',
        "Gunyah RM memory-handle response",
    )

    replace_once(
        r'(?P<i>^[ \t]*)bool end_append;\n'
        r'(?P=i)int ret = 0;\n'
        r'(?P=i)size_t n;',
        r'''{i}bool end_append;
{i}int ret = 0;
{i}size_t n, batch = 0, total_entries = n_mem_entries;''',
        "Gunyah RM append-loop declarations",
    )

    replace_once(
        r'(?P<i>^[ \t]*)ret = _gh_rm_mem_append\(rm, mem_handle, end_append, mem_entries, n\);\n'
        r'(?P=i)if \(ret\)\n'
        r'(?P=i)[ \t]+break;\n'
        r'(?P=i)mem_entries \+= n;\n'
        r'(?P=i)n_mem_entries -= n;',
        r'''{i}pr_info("GH_DIAG rm_append batch begin handle=%u batch=%zu entries=%zu remaining=%zu total=%zu end=%u\n",
{i}\tmem_handle, batch, n, n_mem_entries, total_entries,
{i}\t(unsigned int)end_append);
{i}ret = _gh_rm_mem_append(rm, mem_handle, end_append, mem_entries, n);
{i}pr_info("GH_DIAG rm_append batch end handle=%u batch=%zu ret=%d\n",
{i}\tmem_handle, batch, ret);
{i}if (ret)
{i}\tbreak;
{i}mem_entries += n;
{i}n_mem_entries -= n;
{i}batch++;''',
        "Gunyah RM append-loop body",
    )

    replace_once(
        r'(?P<i>^[ \t]*)ret = gh_rm_call\(rm, GH_RM_RPC_MEM_APPEND, msg, msg_size, NULL, NULL\);\n'
        r'(?P=i)kfree\(msg\);',
        r'''{i}pr_info("GH_DIAG rm_append call begin handle=%u entries=%zu end=%u msg_size=%zu\n",
{i}\tmem_handle, n_mem_entries, (unsigned int)end_append, msg_size);
{i}ret = gh_rm_call(rm, GH_RM_RPC_MEM_APPEND, msg, msg_size, NULL, NULL);
{i}pr_info("GH_DIAG rm_append call end handle=%u entries=%zu end=%u ret=%d\n",
{i}\tmem_handle, n_mem_entries, (unsigned int)end_append, ret);
{i}kfree(msg);''',
        "Gunyah RM MEM_APPEND RPC",
    )

    replace_once(
        r'(?P<i>^[ \t]*)if \(initial_mem_entries != p->n_mem_entries\) \{\n'
        r'(?P<j>[ \t]+)ret = gh_rm_mem_append\(rm, p->mem_handle,\n'
        r'[ \t]+&p->mem_entries\[initial_mem_entries\],\n'
        r'[ \t]+p->n_mem_entries - initial_mem_entries\);\n'
        r'(?P=j)if \(ret\) \{',
        r'''{i}if (initial_mem_entries != p->n_mem_entries) {
{j}pr_info("GH_DIAG rm_append sequence begin handle=%u remaining=%zu total=%zu\n",
{j}\tp->mem_handle, p->n_mem_entries - initial_mem_entries,
{j}\tp->n_mem_entries);
{j}ret = gh_rm_mem_append(rm, p->mem_handle,
{j}\t\t\t       &p->mem_entries[initial_mem_entries],
{j}\t\t\t       p->n_mem_entries - initial_mem_entries);
{j}pr_info("GH_DIAG rm_append sequence end handle=%u ret=%d\n",
{j}\tp->mem_handle, ret);
{j}if (ret) {''',
        "Gunyah RM append sequence",
    )

checks = {
    "initial call begin": source.count("GH_DIAG rm_mem_share call begin") == 1,
    "initial call end": source.count("GH_DIAG rm_mem_share call end") == 1,
    "memory handle": source.count("GH_DIAG rm_mem_share handle") == 1,
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
