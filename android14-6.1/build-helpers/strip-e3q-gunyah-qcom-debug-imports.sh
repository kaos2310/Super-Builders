#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: strip-e3q-gunyah-qcom-debug-imports.sh <kernel-tree>}"
QCOM_SRC="$KERNEL_TREE/drivers/virt/gunyah/gunyah_qcom.c"
test -f "$QCOM_SRC" || { echo "FATAL: gunyah_qcom.c missing: $QCOM_SRC" >&2; exit 1; }

python3 - "$QCOM_SRC" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
text = path.read_text()

patterns = [
    re.compile(
        r'\n\tpr_info\("GH_QCOM_SCM pre_share self_vmid=%u mapped_src_vmid=%u entries=%zu acl=%zu\\n",\n'
        r'\t\tself_vmid, qcom_scm_map_vmid\(self_vmid\),\n'
        r'\t\tmem_parcel->n_mem_entries, mem_parcel->n_acl_entries\);\n'
    ),
    re.compile(
        r'\n\tpr_info\("GH_QCOM_SCM post_reclaim self_vmid=%u mapped_self_vmid=%u entries=%zu acl=%zu\\n",\n'
        r'\t\tself_vmid, qcom_scm_map_vmid\(self_vmid\),\n'
        r'\t\tmem_parcel->n_mem_entries, mem_parcel->n_acl_entries\);\n'
    ),
]
for pat in patterns:
    text, count = pat.subn("\n", text, count=1)
    if count != 1:
        raise SystemExit("FATAL: expected SCM debug marker block was not found exactly once")

path.write_text(text)
PY

! grep -qF 'GH_QCOM_SCM' "$QCOM_SRC"
grep -qF 'gh_rm_get_vmid(rm, &self_vmid)' "$QCOM_SRC"
grep -qF 'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' "$QCOM_SRC"
grep -qF 'src |= BIT_ULL(qcom_scm_map_vmid(vmid));' "$QCOM_SRC"

echo 'e3q gunyah_qcom debug-only printk markers removed; VMID mapping retained'
