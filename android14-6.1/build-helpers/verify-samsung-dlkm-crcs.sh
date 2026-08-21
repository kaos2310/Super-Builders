#!/bin/bash
set -euo pipefail

KERNEL_ROOT="${1:?kernel root}"
BASELINE="${2:?Samsung DLKM CRC baseline}"
REPORT_DIR="${3:?report output directory}"
KMI_MODE="${4:-runtime-compat}"
KMI_PROFILE="${5:-full}"
BASE_COMMIT="9bf8da21bb7e5891bb9b4ef917893a5792874608"
BASE_HELPER="$(mktemp -t verify-samsung-dlkm-crcs.XXXXXX.sh)"
trap 'rm -f "$BASE_HELPER"' EXIT

curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
  "https://raw.githubusercontent.com/kaos2310/Super-Builders/${BASE_COMMIT}/android14-6.1/build-helpers/verify-samsung-dlkm-crcs.sh" \
  -o "$BASE_HELPER"
grep -qF 'Samsung S928B DLKM CRC audit' "$BASE_HELPER"
grep -qF 'strict-rejection' "$BASE_HELPER"

bash "$BASE_HELPER" "$KERNEL_ROOT" "$BASELINE" "$REPORT_DIR" "$KMI_MODE" "$KMI_PROFILE"

# The e3q Gunyah follow-up forces gunyah_qcom.o to obj-m without changing the
# final Samsung-aligned GKI config. Collect the resulting module for live test;
# it is intentionally NOT copied into AnyKernel3 or vendor_boot here.
EXPECTED_RELEASE='6.1.145-android14-11-33419968-abS928BXXS6DZG1'
MODULE=""
declare -A SEEN=()
while IFS= read -r candidate; do
  [[ -s "$candidate" ]] || continue
  resolved=$(realpath "$candidate")
  [[ -z "${SEEN[$resolved]:-}" ]] || continue
  SEEN[$resolved]=1
  strings "$resolved" | grep -qF "vermagic=${EXPECTED_RELEASE}" || continue
  strings "$resolved" | grep -qF 'gh_rm_get_vmid' || continue
  strings "$resolved" | grep -qF 'qcom_scm_assign_mem' || continue
  strings "$resolved" | grep -qF 'GH_QCOM_SCM pre_share self_vmid=' || continue
  strings "$resolved" | grep -qF 'GH_QCOM_SCM post_reclaim self_vmid=' || continue
  MODULE="$resolved"
  break
done < <(
  find -L \
    "$KERNEL_ROOT/out/android14-6.1" \
    "$KERNEL_ROOT/bazel-bin/common" \
    -type f -name 'gunyah_qcom.ko' -print 2>/dev/null || true
)

[[ -n "$MODULE" ]] || {
  echo '::error::Patched gunyah_qcom.ko was not found in kernel build outputs'
  find -L "$KERNEL_ROOT/out/android14-6.1" "$KERNEL_ROOT/bazel-bin/common" \
    -type f -name '*gunyah*qcom*.ko' -print 2>/dev/null | head -30 || true
  exit 1
}

MODULE_DIR="$REPORT_DIR/gunyah-qcom-module"
mkdir -p "$MODULE_DIR"
cp "$MODULE" "$MODULE_DIR/gunyah_qcom.ko"
sha256sum "$MODULE_DIR/gunyah_qcom.ko" > "$MODULE_DIR/gunyah_qcom.ko.sha256"
readelf -p .modinfo "$MODULE_DIR/gunyah_qcom.ko" > "$MODULE_DIR/modinfo.txt"
readelf -Ws "$MODULE_DIR/gunyah_qcom.ko" > "$MODULE_DIR/symbols.txt"
git -C "$KERNEL_ROOT/common" diff -- \
  drivers/virt/gunyah/gunyah_qcom.c \
  drivers/virt/gunyah/cma_compat.c \
  drivers/virt/gunyah/Makefile \
  > "$MODULE_DIR/source.diff"

strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF "vermagic=${EXPECTED_RELEASE}"
strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF 'modversions'
strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF 'aarch64'
strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF 'gh_rm_get_vmid'
strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF 'qcom_scm_assign_mem'
strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF 'GH_QCOM_SCM pre_share self_vmid='
strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF 'GH_QCOM_SCM post_reclaim self_vmid='
grep -qF 'gh_rm_get_vmid' "$MODULE_DIR/symbols.txt"
grep -qF 'qcom_scm_assign_mem' "$MODULE_DIR/symbols.txt"

grep -qF 'gh_rm_get_vmid(rm, &self_vmid)' "$KERNEL_ROOT/common/drivers/virt/gunyah/gunyah_qcom.c"
grep -qF '__free_page(nth_page(chunk->base, i));' "$KERNEL_ROOT/common/drivers/virt/gunyah/cma_compat.c"
! grep -qF 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$KERNEL_ROOT/common/drivers/virt/gunyah/cma_compat.c"

MODULE_SHA=$(awk '{print $1}' "$MODULE_DIR/gunyah_qcom.ko.sha256")
cat >> "$REPORT_DIR/summary.md" <<EOF2

## Patched e3q Gunyah Qualcomm module

- Module: \`gunyah_qcom.ko\`
- SHA-256: \`${MODULE_SHA}\`
- Kernel release: \`${EXPECTED_RELEASE}\`
- SCM RM-VMID mapping marker: present
- \`gh_rm_get_vmid\` dependency: present
- Contig teardown: per-page \`__free_page()\` (no \`free_contig_range()\` warning path)
- Packaging: test artifact only; AnyKernel and vendor_boot remain untouched
EOF2

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  cat >> "$GITHUB_STEP_SUMMARY" <<EOF2

### Patched e3q gunyah_qcom module
- SHA-256: \`${MODULE_SHA}\`
- SCM dynamic-RM-VMID mapping: verified
- Kernel vermagic release: \`${EXPECTED_RELEASE}\`
- Saved inside the Samsung DLKM CRC audit artifact for live ADB testing
EOF2
fi

echo "Patched gunyah_qcom module audited: $MODULE (sha256=$MODULE_SHA)"
