#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-vm-metadata-allocation.sh <kernel-tree>}"
VM_TARGET="$KERNEL_TREE/drivers/virt/gunyah/vm_mgr.c"
RPC_TARGET="$KERNEL_TREE/drivers/virt/gunyah/rsc_mgr_rpc.c"

# Start from the known-good e3q compatibility transform. This wrapper only
# adds the mem-share safety guard and RM diagnostics.
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
        r'(?P<i>^[ \t]*)pr_info\("GH_DIAG mem_share begin vmid=%u label=%u type=%u entries=%zu\\n",\n'
        r'(?P=i)[ \t]+ghvm->vmid, mapping->parcel\.label,\n'
        r'(?P=i)[ \t]+\(unsigned int\)mapping->share_type,\n'
        r'(?P=i)[ \t]+mapping->parcel\.n_mem_entries\);\n',
        re.MULTILINE,
    )
    match = pattern.search(source)
    if not match:
        raise SystemExit(
            "FATAL: cannot locate GH_DIAG mem_share begin marker for safety guard"
        )
    i = match.group("i")
    guard = (
        f"{i}if (mapping->parcel.n_mem_entries > {limit}) {{\n"
        f'{i}    pr_err("GH_DIAG mem_share refused vmid=%u label=%u type=%u entries=%zu limit=%u\\n",\n'
        f"{i}        ghvm->vmid, mapping->parcel.label,\n"
        f"{i}        (unsigned int)mapping->share_type,\n"
        f"{i}        mapping->parcel.n_mem_entries, {limit}U);\n"
        f"{i}    ret = -E2BIG;\n"
        f"{i}    goto err;\n"
        f"{i}}}\n\n"
    )
    source = source[:match.start()] + guard + source[match.start():]

checks = {
    "single guard log": source.count("GH_DIAG mem_share refused") == 1,
    "single begin log": source.count("GH_DIAG mem_share begin") == 1,
    "entry threshold": f"mapping->parcel.n_mem_entries > {limit}" in source,
    "bounded failure": "ret = -E2BIG;" in source,
    "guard precedes share":
        source.index("GH_DIAG mem_share refused") <
        source.index("GH_DIAG mem_share begin"),
    "legacy 512 guard removed":
        "mapping->parcel.n_mem_entries > 512" not in source,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit(
        "FATAL: incomplete Gunyah mem-share guard: " + ", ".join(failed)
    )

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


def function_span(text: str, signature: str):
    start = text.find(signature)
    if start < 0:
        raise SystemExit(f"FATAL: cannot locate Gunyah RM function: {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit(f"FATAL: cannot locate opening brace for: {signature}")
    depth = 0
    for pos in range(brace, len(text)):
        ch = text[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return start, pos + 1
    raise SystemExit(f"FATAL: unterminated Gunyah RM function: {signature}")


def replace_once(block: str, pattern: str, renderer, description: str,
                 flags=re.MULTILINE):
    matches = list(re.finditer(pattern, block, flags))
    if len(matches) != 1:
        raise SystemExit(
            f"FATAL: cannot instrument {description}; found {len(matches)} candidates"
        )
    match = matches[0]
    rendered = renderer(match)
    return block[:match.start()] + rendered + block[match.end():]


def patch_function(text: str, signature: str, transform):
    start, end = function_span(text, signature)
    original = text[start:end]
    patched = transform(original)
    if patched == original:
        raise SystemExit(f"FATAL: no changes made while patching {signature}")
    return text[:start] + patched + text[end:]


if "GH_DIAG rm_mem_share call begin" not in source:
    def patch_append_loop(block: str):
        block = replace_once(
            block,
            r'(?P<i>^[ \t]*)size_t\s+n\s*;',
            lambda m: (
                f"{m.group('i')}size_t n, batch = 0, "
                "total_entries = n_mem_entries;"
            ),
            "Gunyah RM append-loop declaration",
        )

        def render_append_call(m):
            i = m.group("i")
            return (
                f'{i}pr_info("GH_DIAG rm_append batch begin handle=%u '
                f'batch=%zu entries=%zu remaining=%zu total=%zu end=%u\\n",\n'
                f"{i}    mem_handle, batch, n, n_mem_entries, total_entries,\n"
                f"{i}    (unsigned int)end_append);\n"
                f"{i}ret = _gh_rm_mem_append(rm, mem_handle, end_append, "
                "mem_entries, n);\n"
                f'{i}pr_info("GH_DIAG rm_append batch end handle=%u '
                f'batch=%zu ret=%d\\n",\n'
                f"{i}    mem_handle, batch, ret);\n"
                f"{i}batch++;"
            )

        block = replace_once(
            block,
            r'(?P<i>^[ \t]*)ret\s*=\s*_gh_rm_mem_append\s*\(\s*rm\s*,'
            r'\s*mem_handle\s*,\s*end_append\s*,\s*mem_entries\s*,'
            r'\s*n\s*\)\s*;',
            render_append_call,
            "Gunyah RM append call inside append-loop",
        )
        return block

    source = patch_function(
        source,
        "static int gh_rm_mem_append(",
        patch_append_loop,
    )

    def patch_append_rpc(block: str):
        def render_rpc(m):
            i = m.group("i")
            return (
                f'{i}pr_info("GH_DIAG rm_append call begin handle=%u '
                f'entries=%zu end=%u msg_size=%zu\\n",\n'
                f"{i}    mem_handle, n_mem_entries, "
                "(unsigned int)end_append, msg_size);\n"
                f"{i}ret = gh_rm_call(rm, GH_RM_RPC_MEM_APPEND, msg, "
                "msg_size, NULL, NULL);\n"
                f'{i}pr_info("GH_DIAG rm_append call end handle=%u '
                f'entries=%zu end=%u ret=%d\\n",\n'
                f"{i}    mem_handle, n_mem_entries, "
                "(unsigned int)end_append, ret);\n"
                f"{i}kfree(msg);"
            )

        return replace_once(
            block,
            r'(?P<i>^[ \t]*)ret\s*=\s*gh_rm_call\s*\(\s*rm\s*,'
            r'\s*GH_RM_RPC_MEM_APPEND\s*,\s*msg\s*,\s*msg_size\s*,'
            r'\s*NULL\s*,\s*NULL\s*\)\s*;\n'
            r'(?P=i)kfree\s*\(\s*msg\s*\)\s*;',
            render_rpc,
            "Gunyah RM MEM_APPEND RPC",
        )

    source = patch_function(
        source,
        "static int _gh_rm_mem_append(",
        patch_append_rpc,
    )

    def patch_lend_common(block: str):
        block = replace_once(
            block,
            r'(?P<i>^[ \t]*)size_t\s+msg_size\s*=\s*0\s*,'
            r'\s*initial_mem_entries\s*=\s*p->n_mem_entries\s*,'
            r'\s*resp_size\s*;',
            lambda m: (
                f"{m.group('i')}size_t msg_size = 0, "
                "initial_mem_entries = p->n_mem_entries, resp_size = 0;"
            ),
            "Gunyah RM response-size declaration",
        )

        def render_initial_call(m):
            i = m.group("i")
            return (
                f'{i}pr_info("GH_DIAG rm_mem_share call begin rpc=%#x '
                f'label=%u total=%zu initial=%zu append=%u msg_size=%zu\\n",\n'
                f"{i}    (unsigned int)message_id, p->label, p->n_mem_entries, "
                "initial_mem_entries,\n"
                f"{i}    (unsigned int)(initial_mem_entries != "
                "p->n_mem_entries), msg_size);\n"
                f"{i}ret = gh_rm_call(rm, message_id, msg, msg_size, "
                "(void **)&resp, &resp_size);\n"
                f'{i}pr_info("GH_DIAG rm_mem_share call end rpc=%#x '
                f'label=%u ret=%d resp_size=%zu\\n",\n'
                f"{i}    (unsigned int)message_id, p->label, ret, resp_size);\n"
                f"{i}kfree(msg);"
            )

        block = replace_once(
            block,
            r'(?P<i>^[ \t]*)ret\s*=\s*gh_rm_call\s*\(\s*rm\s*,'
            r'\s*message_id\s*,\s*msg\s*,\s*msg_size\s*,'
            r'\s*\(void\s*\*\*\)\s*&resp\s*,\s*&resp_size\s*\)\s*;\n'
            r'(?P=i)kfree\s*\(\s*msg\s*\)\s*;',
            render_initial_call,
            "initial Gunyah RM MEM_SHARE/MEM_LEND call",
        )

        def render_handle(m):
            i = m.group("i")
            return (
                f"{i}p->mem_handle = le32_to_cpu(*resp);\n"
                f'{i}pr_info("GH_DIAG rm_mem_share handle rpc=%#x '
                f'label=%u handle=%u\\n",\n'
                f"{i}    (unsigned int)message_id, p->label, p->mem_handle);\n"
                f"{i}kfree(resp);"
            )

        block = replace_once(
            block,
            r'(?P<i>^[ \t]*)p->mem_handle\s*=\s*le32_to_cpu\s*'
            r'\(\s*\*resp\s*\)\s*;\n'
            r'(?P=i)kfree\s*\(\s*resp\s*\)\s*;',
            render_handle,
            "Gunyah RM memory-handle response",
        )

        def render_sequence(m):
            i = m.group("i")
            j = m.group("j")
            return (
                f"{i}if (initial_mem_entries != p->n_mem_entries) {{\n"
                f'{j}pr_info("GH_DIAG rm_append sequence begin handle=%u '
                f'remaining=%zu total=%zu\\n",\n'
                f"{j}    p->mem_handle, "
                "p->n_mem_entries - initial_mem_entries,\n"
                f"{j}    p->n_mem_entries);\n"
                f"{j}ret = gh_rm_mem_append(rm, p->mem_handle,\n"
                f"{j}    &p->mem_entries[initial_mem_entries],\n"
                f"{j}    p->n_mem_entries - initial_mem_entries);\n"
                f'{j}pr_info("GH_DIAG rm_append sequence end handle=%u '
                f'ret=%d\\n",\n'
                f"{j}    p->mem_handle, ret);\n"
                f"{j}if (ret) {{"
            )

        block = replace_once(
            block,
            r'(?P<i>^[ \t]*)if\s*\(\s*initial_mem_entries\s*!='
            r'\s*p->n_mem_entries\s*\)\s*\{\n'
            r'(?P<j>[ \t]+)ret\s*=\s*gh_rm_mem_append\s*'
            r'\(\s*rm\s*,\s*p->mem_handle\s*,\s*\n'
            r'[ \t]*&p->mem_entries\s*\[\s*initial_mem_entries\s*\]'
            r'\s*,\s*\n'
            r'[ \t]*p->n_mem_entries\s*-\s*initial_mem_entries\s*'
            r'\)\s*;\n'
            r'(?P=j)if\s*\(\s*ret\s*\)\s*\{',
            render_sequence,
            "Gunyah RM append sequence",
        )
        return block

    source = patch_function(
        source,
        "static int gh_rm_mem_lend_common(",
        patch_lend_common,
    )

batch_define = re.search(
    r'(?m)^[ \t]*#[ \t]*define[ \t]+GH_RM_MAX_MEM_ENTRIES[ \t]+'
    r'(?:\([ \t]*)?512(?:[uU](?:[lL]{1,2})?)?(?:[ \t]*\))?'
    r'[ \t]*(?:/\*.*\*/)?$',
    source,
)
append_loop_uses_batch = re.search(
    r'\bn\s*=\s*GH_RM_MAX_MEM_ENTRIES\s*;',
    source,
) is not None
initial_share_uses_batch = re.search(
    r'\binitial_mem_entries\s*=\s*GH_RM_MAX_MEM_ENTRIES\s*;',
    source,
) is not None
literal_tab_escape = re.search(r'(?m)^[ \t]*\\t', source) is not None

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
    "upstream batch size retained": batch_define is not None,
    "append loop still uses batch macro": append_loop_uses_batch,
    "initial share still uses batch macro": initial_share_uses_batch,
    "no literal tab escapes in C": not literal_tab_escape,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit(
        "FATAL: incomplete Gunyah RM diagnostics: " + ", ".join(failed)
    )

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

python3 - "$RPC_TARGET" <<'PY'
from pathlib import Path
import re
import sys

source = Path(sys.argv[1]).read_text()
if not re.search(
    r'(?m)^[ \t]*#[ \t]*define[ \t]+GH_RM_MAX_MEM_ENTRIES[ \t]+'
    r'(?:\([ \t]*)?512(?:[uU](?:[lL]{1,2})?)?(?:[ \t]*\))?',
    source,
):
    raise SystemExit("FATAL: GH_RM_MAX_MEM_ENTRIES is no longer 512")
if re.search(r'(?m)^[ \t]*\\t', source):
    raise SystemExit("FATAL: literal tab escape leaked into generated C")
PY

echo 'e3q Gunyah diagnostics verified: guard=8192 extents, RM batch=512 entries, failure=-E2BIG'
