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

# The e3q follow-up builds the two stock vendor_boot dependencies as additional
# Kleaf-declared test outputs, while the flashable AnyKernel continues to carry
# only Image. Collect and audit the patched consumer module for a live rmmod/
# insmod test after the matching new kernel has been flashed.
EXPECTED_RELEASE='6.1.145-android14-11-33419968-abS928BXXS6DZG1'
STOCK_MODVERSIONS="$GITHUB_WORKSPACE/$VERSION_DIR/e3q-gunyah-qcom-stock-modversions.tsv"
test -s "$STOCK_MODVERSIONS" || { echo "::error::Stock gunyah_qcom modversion baseline missing"; exit 1; }

MODULE=""
SCM_MODULE=""
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
  find -L "$KERNEL_ROOT/out/android14-6.1" "$KERNEL_ROOT/bazel-bin/common" \
    -type f -name 'gunyah_qcom.ko' -print 2>/dev/null || true
)

while IFS= read -r candidate; do
  [[ -s "$candidate" ]] || continue
  resolved=$(realpath "$candidate")
  strings "$resolved" | grep -qF "vermagic=${EXPECTED_RELEASE}" || continue
  SCM_MODULE="$resolved"
  break
done < <(
  find -L "$KERNEL_ROOT/out/android14-6.1" "$KERNEL_ROOT/bazel-bin/common" \
    -type f -name 'qcom-scm.ko' -print 2>/dev/null || true
)

[[ -n "$MODULE" ]] || {
  echo '::error::Patched gunyah_qcom.ko was not found in kernel build outputs'
  find -L "$KERNEL_ROOT/out/android14-6.1" "$KERNEL_ROOT/bazel-bin/common" \
    -type f -name '*gunyah*qcom*.ko' -print 2>/dev/null | head -30 || true
  exit 1
}
[[ -n "$SCM_MODULE" ]] || {
  echo '::error::Build-only qcom-scm.ko dependency was not found in kernel build outputs'
  find -L "$KERNEL_ROOT/out/android14-6.1" "$KERNEL_ROOT/bazel-bin/common" \
    -type f -name '*qcom*scm*.ko' -print 2>/dev/null | head -30 || true
  exit 1
}

MODULE_DIR="$REPORT_DIR/gunyah-qcom-module"
mkdir -p "$MODULE_DIR"
cp "$MODULE" "$MODULE_DIR/gunyah_qcom.ko"
sha256sum "$MODULE_DIR/gunyah_qcom.ko" > "$MODULE_DIR/gunyah_qcom.ko.sha256"
sha256sum "$SCM_MODULE" > "$MODULE_DIR/qcom-scm-build-only.ko.sha256"
readelf -p .modinfo "$MODULE_DIR/gunyah_qcom.ko" > "$MODULE_DIR/modinfo.txt"
readelf -Ws "$MODULE_DIR/gunyah_qcom.ko" > "$MODULE_DIR/symbols.txt"
git -C "$KERNEL_ROOT/common" diff -- \
  drivers/virt/gunyah/gunyah_qcom.c \
  drivers/virt/gunyah/cma_compat.c \
  drivers/virt/gunyah/Makefile \
  drivers/firmware/Makefile \
  modules.bzl \
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

# Parse ELF64 __versions without target-architecture objcopy. Every arm64
# modversion_info record is 64 bytes: 8-byte little-endian CRC + 56-byte name.
python3 - "$MODULE_DIR/gunyah_qcom.ko" "$STOCK_MODVERSIONS" "$MODULE_DIR/modversions.tsv" <<'PY'
from pathlib import Path
import struct
import sys

module = Path(sys.argv[1])
baseline = Path(sys.argv[2])
report = Path(sys.argv[3])
data = module.read_bytes()
if data[:4] != b"\x7fELF" or data[4] != 2 or data[5] != 1:
    raise SystemExit("FATAL: gunyah_qcom.ko is not little-endian ELF64")

shoff = struct.unpack_from("<Q", data, 0x28)[0]
shentsize = struct.unpack_from("<H", data, 0x3A)[0]
shnum = struct.unpack_from("<H", data, 0x3C)[0]
shstrndx = struct.unpack_from("<H", data, 0x3E)[0]
if not shoff or shentsize < 64 or not shnum or shstrndx >= shnum:
    raise SystemExit("FATAL: invalid ELF section table")

def sh(index):
    off = shoff + index * shentsize
    name = struct.unpack_from("<I", data, off)[0]
    sec_off = struct.unpack_from("<Q", data, off + 24)[0]
    sec_size = struct.unpack_from("<Q", data, off + 32)[0]
    return name, sec_off, sec_size

_, str_off, str_size = sh(shstrndx)
strtab = data[str_off:str_off + str_size]
def cstr(buf, off):
    end = buf.find(b"\0", off)
    return buf[off:end if end >= 0 else len(buf)].decode("utf-8", "replace")

vers = None
for idx in range(shnum):
    name_off, sec_off, sec_size = sh(idx)
    if cstr(strtab, name_off) == "__versions":
        vers = data[sec_off:sec_off + sec_size]
        break
if vers is None or len(vers) % 64:
    raise SystemExit("FATAL: invalid or missing __versions section")

actual = {}
for off in range(0, len(vers), 64):
    rec = vers[off:off + 64]
    crc = struct.unpack_from("<Q", rec, 0)[0] & 0xffffffff
    name = rec[8:].split(b"\0", 1)[0].decode("utf-8", "strict")
    if name:
        actual[name] = crc

expected = {}
for raw in baseline.read_text().splitlines():
    if not raw or raw.startswith("#"):
        continue
    name, crc = raw.split("\t")[:2]
    expected[name] = int(crc, 16)

errors = []
for name, crc in expected.items():
    got = actual.get(name)
    if got is None:
        errors.append(f"missing stock import {name}")
    elif got != crc:
        errors.append(f"CRC mismatch {name}: stock=0x{crc:08x} build=0x{got:08x}")

for required in ("gh_rm_get_vmid", "qcom_scm_assign_mem"):
    if required not in actual:
        errors.append(f"missing required patched import {required}")

report.write_text(
    "symbol\tcrc\n" +
    "".join(f"{name}\t0x{crc:08x}\n" for name, crc in sorted(actual.items()))
)
if errors:
    raise SystemExit("FATAL: gunyah_qcom stock modversion audit failed: " + "; ".join(errors))
print(f"Verified {len(expected)} stock import CRCs plus gh_rm_get_vmid in patched gunyah_qcom.ko")
PY

grep -qF $'qcom_scm_assign_mem\t0xcdaced8a' "$MODULE_DIR/modversions.tsv"
grep -qF $'module_layout\t0xea759d7f' "$MODULE_DIR/modversions.tsv"
grep -qF 'gh_rm_get_vmid' "$MODULE_DIR/modversions.tsv"

grep -qF 'gh_rm_get_vmid(rm, &self_vmid)' "$KERNEL_ROOT/common/drivers/virt/gunyah/gunyah_qcom.c"
grep -qF '__free_page(nth_page(chunk->base, i));' "$KERNEL_ROOT/common/drivers/virt/gunyah/cma_compat.c"
! grep -qF 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$KERNEL_ROOT/common/drivers/virt/gunyah/cma_compat.c"
grep -qF '"drivers/firmware/qcom-scm.ko",' "$KERNEL_ROOT/common/modules.bzl"
grep -qF '"drivers/virt/gunyah/gunyah_qcom.ko",' "$KERNEL_ROOT/common/modules.bzl"

MODULE_SHA=$(awk '{print $1}' "$MODULE_DIR/gunyah_qcom.ko.sha256")
SCM_SHA=$(awk '{print $1}' "$MODULE_DIR/qcom-scm-build-only.ko.sha256")
cat >> "$REPORT_DIR/summary.md" <<EOF2

## Patched e3q Gunyah Qualcomm module

- Module: \`gunyah_qcom.ko\`
- SHA-256: \`${MODULE_SHA}\`
- Build-only dependency qcom-scm SHA-256: \`${SCM_SHA}\`
- Kernel release: \`${EXPECTED_RELEASE}\`
- All 11 stock DZG1 gunyah_qcom import CRCs: exact
- \`qcom_scm_assign_mem\` stock CRC: \`0xcdaced8a\`
- New \`gh_rm_get_vmid\` import: present
- SCM RM-VMID mapping runtime markers: present
- Contig teardown: per-page \`__free_page()\` (no \`free_contig_range()\` warning path)
- Packaging: gunyah_qcom is test artifact only; AnyKernel and vendor_boot remain untouched
EOF2

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  cat >> "$GITHUB_STEP_SUMMARY" <<EOF2

### Patched e3q gunyah_qcom module
- SHA-256: \`${MODULE_SHA}\`
- 11/11 stock DZG1 import CRCs exact; qcom_scm_assign_mem=0xcdaced8a
- SCM dynamic-RM-VMID mapping + gh_rm_get_vmid: verified
- Kernel vermagic release: \`${EXPECTED_RELEASE}\`
- Saved inside the Samsung DLKM CRC audit artifact for live ADB testing
EOF2
fi

echo "Patched gunyah_qcom module audited: $MODULE (sha256=$MODULE_SHA)"
