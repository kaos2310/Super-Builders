#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-qcom-vmid-compat.sh <kernel-tree>}"
BASE_COMMIT="d2cc27a6136839a9f4a62c3d45975d19ce20e0ae"
TMP_DIR="$(mktemp -d -t e3q-boot-context-fix.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

BASE_HELPER="$TMP_DIR/apply-e3q-gunyah-qcom-vmid-compat.sh"
curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
  "https://raw.githubusercontent.com/kaos2310/Super-Builders/${BASE_COMMIT}/android14-6.1/build-helpers/apply-e3q-gunyah-qcom-vmid-compat.sh" \
  -o "$BASE_HELPER"

test -s "$BASE_HELPER" || {
  echo 'FATAL: pinned boot-context helper is empty' >&2
  exit 1
}
bash -n "$BASE_HELPER"

# d2cc27a introduced the runtime-required boot-context backport. Adapt only
# source-shape assumptions that differ on the exact Samsung/AOSP tree used by
# this workflow. The outer vm-metadata helper owns the 8192-entry guard: it
# deliberately removes that guard before invoking this QCOM follow-up and
# restores + validates the exact saved block immediately afterwards. Therefore
# this nested helper must not reject the intentional temporary guard absence.
python3 - "$BASE_HELPER" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text()

old_import = "from pathlib import Path\nimport sys\n"
new_import = "from pathlib import Path\nimport re\nimport sys\n"
if old_import not in text:
    raise SystemExit("FATAL: pinned helper Python import anchor changed")
text = text.replace(old_import, new_import, 1)

# Samsung/AOSP aligns the RM opcode defines with tabs/extra spaces.
old = """if 'GH_RM_RPC_VM_SET_BOOT_CONTEXT' not in rpc:\n    anchor = '#define GH_RM_RPC_VM_GET_VMID 0x56000024\\n'\n    if anchor not in rpc:\n        raise SystemExit('FATAL: RM GET_VMID opcode anchor missing')\n    rpc = rpc.replace(anchor, anchor + '#define GH_RM_RPC_VM_SET_BOOT_CONTEXT 0x56000031\\n', 1)\n"""
new = """if 'GH_RM_RPC_VM_SET_BOOT_CONTEXT' not in rpc:\n    pattern = re.compile(\n        r'(?m)^#define[ \\t]+GH_RM_RPC_VM_GET_VMID[ \\t]+0x56000024[ \\t]*\\n'\n    )\n    matches = list(pattern.finditer(rpc))\n    if len(matches) != 1:\n        raise SystemExit(\n            f'FATAL: expected one RM GET_VMID opcode anchor, found {len(matches)}'\n        )\n    end = matches[0].end()\n    rpc = (\n        rpc[:end]\n        + '#define GH_RM_RPC_VM_SET_BOOT_CONTEXT 0x56000031\\n'\n        + rpc[end:]\n    )\n"""
if text.count(old) != 1:
    raise SystemExit(
        f"FATAL: expected one strict GET_VMID matcher in pinned helper, found {text.count(old)}"
    )
text = text.replace(old, new, 1)

# Match the upstream Gunyah boot-context xarray value representation.
for old_cast, new_cast in (
    ('(void *)(uintptr_t)boot_ctx->value', '(void *)boot_ctx->value'),
    ('(u64)(uintptr_t)entry', '(u64)entry'),
):
    if text.count(old_cast) != 1:
        raise SystemExit(
            f"FATAL: expected one boot-context cast {old_cast!r}, found {text.count(old_cast)}"
        )
    text = text.replace(old_cast, new_cast, 1)

# During this helper call the outer wrapper has intentionally removed only the
# 8192 guard block. Keep every other fail-closed assertion, but defer this one
# guard assertion to the outer wrapper which restores the exact saved text.
guard_check = "require_fixed 'mapping->parcel.n_mem_entries > 8192' \"$VM_SRC\" '8192 mem-share safety guard'\n"
if text.count(guard_check) != 1:
    raise SystemExit(
        f"FATAL: expected one nested 8192 guard assertion, found {text.count(guard_check)}"
    )
text = text.replace(
    guard_check,
    "echo 'e3q nested QCOM/boot-context validation: 8192 guard check deferred to outer restore gate'\n",
    1,
)

# Ensure the inner fail-closed audit still recognizes the inserted opcode and
# that all unrelated integrity gates remain present.
required = (
    'GH_RM_RPC_VM_SET_BOOT_CONTEXT 0x56000031',
    "require_fixed 'GH_DIAG mem_share begin'",
    "require_fixed 'GH_RM_RPC_MEM_APPEND'",
    "require_fixed 'GH_DIAG rm_append sequence begin'",
    "require_fixed 'static u16 qcom_scm_map_vmid(u16 vmid)'",
    "require_absent 'GH_QCOM_DIAG'",
)
missing = [token for token in required if token not in text]
if missing:
    raise SystemExit('FATAL: nested helper lost required integrity gates: ' + ', '.join(missing))

path.write_text(text)
PY

bash -n "$BASE_HELPER"

# Execute the complete d2cc27a QCOM + boot-context implementation. The caller
# restores the exact 8192 guard immediately after this returns, and performs
# its own final guard/MEM_APPEND/bounded-backing/SCM/KMI assertions before any
# kernel compilation starts.
bash "$BASE_HELPER" "$KERNEL_TREE"

echo 'e3q Gunyah QCOM/boot-context helper complete; outer 8192 guard restore gate remains authoritative'
