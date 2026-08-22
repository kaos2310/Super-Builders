#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-qcom-vmid-compat.sh <kernel-tree>}"
BASE_COMMIT="f314a3274b567352a2ad17a76b1c5229b0e9c241"
TMP_DIR="$(mktemp -d -t e3q-qcom-vmid-diag.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

BASE_HELPER="$TMP_DIR/apply-e3q-gunyah-qcom-vmid-compat.sh"
curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
  "https://raw.githubusercontent.com/kaos2310/Super-Builders/${BASE_COMMIT}/android14-6.1/build-helpers/apply-e3q-gunyah-qcom-vmid-compat.sh" \
  -o "$BASE_HELPER"

test -s "$BASE_HELPER" || { echo 'FATAL: pinned e3q QCOM baseline helper is empty' >&2; exit 1; }
bash -n "$BASE_HELPER"
for token in \
  'static u16 qcom_scm_map_vmid(u16 vmid)' \
  'gh_rm_get_vmid(rm, &self_vmid)' \
  'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' \
  'new_perms[n].vmid = qcom_scm_map_vmid(vmid);'; do
  grep -qF "$token" "$BASE_HELPER" || {
    echo "FATAL: pinned e3q QCOM baseline missing expected VMID token: $token" >&2
    exit 1
  }
done

# Preserve the runtime-proven SCM/VMID mapping, provider build, module packaging
# and safe bounded-backing teardown exactly as they existed at BASE_COMMIT.
bash "$BASE_HELPER" "$KERNEL_TREE"

QCOM_SRC="$KERNEL_TREE/drivers/virt/gunyah/gunyah_qcom.c"
test -s "$QCOM_SRC" || { echo "FATAL: missing Gunyah QCOM source: $QCOM_SRC" >&2; exit 1; }

# Add observation-only diagnostics. Do not alter VMID mapping, permissions,
# memory ownership, RM messages, the 8192 safety guard, or IRQ/VCPU behavior.
python3 - "$QCOM_SRC" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
source = path.read_text()


def span(text: str, signature: str):
    start = text.find(signature)
    if start < 0:
        raise SystemExit(f"FATAL: cannot locate {signature}")
    brace = text.find("{", start)
    if brace < 0:
        raise SystemExit(f"FATAL: no opening brace for {signature}")
    depth = 0
    for pos in range(brace, len(text)):
        ch = text[pos]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return start, pos + 1
    raise SystemExit(f"FATAL: unterminated {signature}")


def replace_once(block: str, old: str, new: str, label: str):
    count = block.count(old)
    if count != 1:
        raise SystemExit(f"FATAL: {label}: expected one anchor, found {count}")
    return block.replace(old, new, 1)


if "GH_QCOM_DIAG pre_share" not in source:
    start, end = span(source, "static int qcom_scm_gh_rm_pre_mem_share(")
    block = source[start:end]

    vmid_anchor = (
        "\tret = gh_rm_get_vmid(rm, &self_vmid);\n"
        "\tif (ret)\n"
        "\t\treturn ret;\n"
    )
    block = replace_once(
        block,
        vmid_anchor,
        vmid_anchor
        + "\n\tpr_info(\"GH_QCOM_DIAG pre_share self_vmid=%u mapped_self=%u acl=%zu mem=%zu\\n\",\n"
        + "\t\t(unsigned int)self_vmid,\n"
        + "\t\t(unsigned int)qcom_scm_map_vmid(self_vmid),\n"
        + "\t\tmem_parcel->n_acl_entries, mem_parcel->n_mem_entries);\n",
        "pre_share self VMID diagnostic",
    )

    acl_anchor = "\t\tnew_perms[n].vmid = qcom_scm_map_vmid(vmid);\n"
    block = replace_once(
        block,
        acl_anchor,
        acl_anchor
        + "\t\tpr_info(\"GH_QCOM_DIAG acl[%d] raw_vmid=%u mapped_vmid=%u perms=0x%x\\n\",\n"
        + "\t\t\tn, (unsigned int)vmid, (unsigned int)new_perms[n].vmid,\n"
        + "\t\t\t(unsigned int)mem_parcel->acl_entries[n].perms);\n",
        "ACL VMID diagnostic",
    )

    src_anchor = "\tsrc = BIT_ULL(qcom_scm_map_vmid(self_vmid));\n"
    block = replace_once(
        block,
        src_anchor,
        src_anchor
        + "\tpr_info(\"GH_QCOM_DIAG source self_vmid=%u mapped_self=%u src=0x%llx\\n\",\n"
        + "\t\t(unsigned int)self_vmid,\n"
        + "\t\t(unsigned int)qcom_scm_map_vmid(self_vmid),\n"
        + "\t\t(unsigned long long)src);\n",
        "SCM source mask diagnostic",
    )

    fail_anchor = "\t\tif (ret)\n\t\t\tbreak;\n"
    block = replace_once(
        block,
        fail_anchor,
        "\t\tif (ret) {\n"
        "\t\t\tpr_err(\"GH_QCOM_DIAG assign_mem FAILED index=%d ret=%d src=0x%llx\\n\",\n"
        "\t\t\t\ti, ret, (unsigned long long)src);\n"
        "\t\t\tbreak;\n"
        "\t\t}\n",
        "pre_share SCM failure diagnostic",
    )

    source = source[:start] + block + source[end:]

if "GH_QCOM_DIAG reclaim" not in source:
    start, end = span(source, "static int qcom_scm_gh_rm_post_mem_reclaim(")
    block = source[start:end]

    loop_anchor = "\tfor (i = 0; i < mem_parcel->n_mem_entries; i++) {\n"
    block = replace_once(
        block,
        loop_anchor,
        "\tpr_info(\"GH_QCOM_DIAG reclaim self_vmid=%u mapped_self=%u src=0x%llx acl=%zu mem=%zu\\n\",\n"
        "\t\t(unsigned int)self_vmid,\n"
        "\t\t(unsigned int)qcom_scm_map_vmid(self_vmid),\n"
        "\t\t(unsigned long long)src, mem_parcel->n_acl_entries,\n"
        "\t\tmem_parcel->n_mem_entries);\n\n"
        + loop_anchor,
        "reclaim VMID diagnostic",
    )

    warn_anchor = "\t\tWARN_ON_ONCE(ret);\n"
    block = replace_once(
        block,
        warn_anchor,
        "\t\tif (ret)\n"
        "\t\t\tpr_err(\"GH_QCOM_DIAG reclaim assign_mem FAILED index=%d ret=%d src=0x%llx\\n\",\n"
        "\t\t\t\ti, ret, (unsigned long long)src);\n"
        + warn_anchor,
        "reclaim SCM failure diagnostic",
    )

    source = source[:start] + block + source[end:]

path.write_text(source)
PY

require_fixed() {
  local needle="$1" file="$2" label="$3"
  grep -qF "$needle" "$file" || {
    echo "FATAL: missing ${label}: ${needle} in ${file}" >&2
    exit 1
  }
}

# Fail closed: diagnostics must coexist with the already-proven functional path.
for spec in \
  'static u16 qcom_scm_map_vmid(u16 vmid)|SCM VMID mapping helper' \
  'gh_rm_get_vmid(rm, &self_vmid)|dynamic RM self-VMID lookup' \
  'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));|SCM source VMID mapping' \
  'new_perms[n].vmid = qcom_scm_map_vmid(vmid);|SCM destination VMID mapping' \
  'GH_QCOM_DIAG pre_share self_vmid=%u mapped_self=%u acl=%zu mem=%zu|pre-share VMID diagnostic' \
  'GH_QCOM_DIAG acl[%d] raw_vmid=%u mapped_vmid=%u perms=0x%x|ACL mapping diagnostic' \
  'GH_QCOM_DIAG source self_vmid=%u mapped_self=%u src=0x%llx|SCM source-mask diagnostic' \
  'GH_QCOM_DIAG assign_mem FAILED index=%d ret=%d src=0x%llx|SCM share failure diagnostic' \
  'GH_QCOM_DIAG reclaim self_vmid=%u mapped_self=%u src=0x%llx acl=%zu mem=%zu|SCM reclaim diagnostic' \
  'GH_QCOM_DIAG reclaim assign_mem FAILED index=%d ret=%d src=0x%llx|SCM reclaim failure diagnostic'; do
  needle="${spec%%|*}"
  label="${spec#*|}"
  require_fixed "$needle" "$QCOM_SRC" "$label"
done

if grep -qF 'GH_QCOM_SCM' "$QCOM_SRC"; then
  echo 'FATAL: abandoned GH_QCOM_SCM workaround reintroduced' >&2
  exit 1
fi

echo 'e3q Gunyah QCOM VMID path preserved; GH_QCOM_DIAG observation-only instrumentation enabled'
