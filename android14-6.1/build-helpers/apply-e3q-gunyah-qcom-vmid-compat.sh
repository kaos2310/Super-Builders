#!/usr/bin/env bash
set -euo pipefail

KERNEL_TREE="${1:?usage: apply-e3q-gunyah-qcom-vmid-compat.sh <kernel-tree>}"
BASE_COMMIT="f314a3274b567352a2ad17a76b1c5229b0e9c241"
TMP_DIR="$(mktemp -d -t e3q-qcom-vmid-base.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

BASE_HELPER="$TMP_DIR/apply-e3q-gunyah-qcom-vmid-compat.sh"
curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
  "https://raw.githubusercontent.com/kaos2310/Super-Builders/${BASE_COMMIT}/android14-6.1/build-helpers/apply-e3q-gunyah-qcom-vmid-compat.sh" \
  -o "$BASE_HELPER"

test -s "$BASE_HELPER" || { echo 'FATAL: pinned e3q QCOM baseline helper is empty' >&2; exit 1; }
bash -n "$BASE_HELPER"

# The pinned helper is the runtime-proven SCM/VMID implementation. Keep the
# functional path intact and deliberately do not inject pr_info()/pr_err()
# diagnostics: gunyah_qcom must not gain the debug-only _printk import.
for token in \
  'static u16 qcom_scm_map_vmid(u16 vmid)' \
  'gh_rm_get_vmid(rm, &self_vmid)' \
  'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' \
  'new_perms[n].vmid = qcom_scm_map_vmid(vmid);' \
  'src |= BIT_ULL(qcom_scm_map_vmid(vmid));'; do
  grep -qF "$token" "$BASE_HELPER" || {
    echo "FATAL: pinned e3q QCOM baseline missing expected VMID token: $token" >&2
    exit 1
  }
done

bash "$BASE_HELPER" "$KERNEL_TREE"

QCOM_SRC="$KERNEL_TREE/drivers/virt/gunyah/gunyah_qcom.c"
test -s "$QCOM_SRC" || { echo "FATAL: missing Gunyah QCOM source: $QCOM_SRC" >&2; exit 1; }

require_fixed() {
  local needle="$1" file="$2" label="$3"
  grep -qF "$needle" "$file" || {
    echo "FATAL: missing ${label}: ${needle} in ${file}" >&2
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

# Fail closed on the proven functional semantics while keeping the strict
# modversion audit meaningful.
require_fixed 'static u16 qcom_scm_map_vmid(u16 vmid)' "$QCOM_SRC" 'SCM VMID mapping helper'
require_fixed 'gh_rm_get_vmid(rm, &self_vmid)' "$QCOM_SRC" 'dynamic RM self-VMID lookup'
require_fixed 'src = BIT_ULL(qcom_scm_map_vmid(self_vmid));' "$QCOM_SRC" 'SCM source VMID mapping'
require_fixed 'new_perms[n].vmid = qcom_scm_map_vmid(vmid);' "$QCOM_SRC" 'SCM destination VMID mapping'
require_fixed 'src |= BIT_ULL(qcom_scm_map_vmid(vmid));' "$QCOM_SRC" 'SCM reclaim VMID mapping'
require_absent 'GH_QCOM_DIAG' "$QCOM_SRC" 'printk-based runtime diagnostics'
require_absent 'GH_QCOM_SCM' "$QCOM_SRC" 'abandoned GH_QCOM_SCM workaround'

echo 'e3q Gunyah QCOM VMID path preserved; printk diagnostics disabled for strict modversion audit'
