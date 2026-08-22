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

# d2cc27a introduced the runtime-required boot-context backport, but its first
# source edit matched the GET_VMID #define with one exact whitespace spelling.
# The Samsung/AOSP generated source uses aligned whitespace, so the helper
# stopped before compilation even though the opcode is present. Patch only the
# helper's source matcher; preserve all runtime-proven Gunyah functionality.
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

old = """if 'GH_RM_RPC_VM_SET_BOOT_CONTEXT' not in rpc:\n    anchor = '#define GH_RM_RPC_VM_GET_VMID 0x56000024\\n'\n    if anchor not in rpc:\n        raise SystemExit('FATAL: RM GET_VMID opcode anchor missing')\n    rpc = rpc.replace(anchor, anchor + '#define GH_RM_RPC_VM_SET_BOOT_CONTEXT 0x56000031\\n', 1)\n"""
new = """if 'GH_RM_RPC_VM_SET_BOOT_CONTEXT' not in rpc:\n    pattern = re.compile(\n        r'(?m)^#define[ \\t]+GH_RM_RPC_VM_GET_VMID[ \\t]+0x56000024[ \\t]*\\n'\n    )\n    matches = list(pattern.finditer(rpc))\n    if len(matches) != 1:\n        raise SystemExit(\n            f'FATAL: expected one RM GET_VMID opcode anchor, found {len(matches)}'\n        )\n    end = matches[0].end()\n    rpc = (\n        rpc[:end]\n        + '#define GH_RM_RPC_VM_SET_BOOT_CONTEXT 0x56000031\\n'\n        + rpc[end:]\n    )\n"""
if text.count(old) != 1:
    raise SystemExit(
        f"FATAL: expected one strict GET_VMID matcher in pinned helper, found {text.count(old)}"
    )
text = text.replace(old, new, 1)

# Match the upstream v17 implementation exactly for xarray value storage.
for old_cast, new_cast in (
    ('(void *)(uintptr_t)boot_ctx->value', '(void *)boot_ctx->value'),
    ('(u64)(uintptr_t)entry', '(u64)entry'),
):
    if text.count(old_cast) != 1:
        raise SystemExit(
            f"FATAL: expected one boot-context cast {old_cast!r}, found {text.count(old_cast)}"
        )
    text = text.replace(old_cast, new_cast, 1)

# Ensure the inner fail-closed check will recognize the generated opcode line.
if "GH_RM_RPC_VM_SET_BOOT_CONTEXT 0x56000031" not in text:
    raise SystemExit("FATAL: patched helper no longer contains audit-compatible boot-context opcode")

path.write_text(text)
PY

bash -n "$BASE_HELPER"

# Execute the complete d2cc27a implementation after fixing only its source
# matching/cast details. The inner helper still validates QCOM SCM VMID mapping,
# boot-context UAPI/RPC/lifecycle integration, MEM_APPEND, and the 8192 guard.
bash "$BASE_HELPER" "$KERNEL_TREE"

echo 'e3q Gunyah boot-context helper completed with whitespace-tolerant RM opcode matching'
