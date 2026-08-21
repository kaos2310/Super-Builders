#!/usr/bin/env bash
set -euo pipefail

KERNEL_ROOT="${1:?kernel root}"
REPORT_DIR="${2:?report dir}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
EXPECTED_RELEASE='6.1.145-android14-11-33419968-abS928BXXS6DZG1'
STOCK_MODVERSIONS="$SCRIPT_DIR/../e3q-gunyah-qcom-stock-modversions.tsv"
ABI_LIST="$KERNEL_ROOT/common/android/abi_gki_aarch64"
QCOM_SRC="$KERNEL_ROOT/common/drivers/virt/gunyah/gunyah_qcom.c"
BACKING_SRC="$KERNEL_ROOT/common/drivers/virt/gunyah/cma_compat.c"

test -s "$STOCK_MODVERSIONS" || { echo '::error::Stock gunyah_qcom modversion baseline missing'; exit 1; }
test -s "$ABI_LIST" || { echo '::error::Final GKI ABI symbol list missing'; exit 1; }
grep -Eq '^[[:space:]]*gh_rm_get_vmid[[:space:]]*$' "$ABI_LIST" || {
  echo '::error::gh_rm_get_vmid is missing from final GKI KMI symbol list'; exit 1;
}

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
  if strings "$resolved" | grep -qF 'GH_QCOM_SCM'; then
    continue
  fi
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
  android/abi_gki_aarch64 \
  drivers/virt/gunyah/gunyah_qcom.c \
  drivers/virt/gunyah/cma_compat.c \
  drivers/virt/gunyah/Makefile \
  drivers/firmware/Makefile \
  modules.bzl > "$MODULE_DIR/source.diff"

strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF "vermagic=${EXPECTED_RELEASE}"
strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF 'modversions'
strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF 'aarch64'
strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF 'gh_rm_get_vmid'
strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF 'qcom_scm_assign_mem'
! strings "$MODULE_DIR/gunyah_qcom.ko" | grep -qF 'GH_QCOM_SCM'
grep -qF 'gh_rm_get_vmid' "$MODULE_DIR/symbols.txt"
grep -qF 'qcom_scm_assign_mem' "$MODULE_DIR/symbols.txt"

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
    return (
        struct.unpack_from("<I", data, off)[0],
        struct.unpack_from("<Q", data, off + 24)[0],
        struct.unpack_from("<Q", data, off + 32)[0],
    )

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
if "gh_rm_get_vmid" not in actual:
    errors.append("missing required patched import gh_rm_get_vmid")
if "_printk" in actual:
    errors.append("unexpected debug-only _printk import")

report.write_text(
    "symbol\tcrc\n" +
    "".join(f"{name}\t0x{crc:08x}\n" for name, crc in sorted(actual.items()))
)
if errors:
    raise SystemExit("FATAL: gunyah_qcom modversion audit failed: " + "; ".join(errors))
print(f"Verified {len(expected)} stock import CRCs + gh_rm_get_vmid; no _printk import")
PY

grep -qF $'qcom_scm_assign_mem\t0xcdaced8a' "$MODULE_DIR/modversions.tsv"
grep -qF $'module_layout\t0xea759d7f' "$MODULE_DIR/modversions.tsv"
grep -qF 'gh_rm_get_vmid' "$MODULE_DIR/modversions.tsv"
! grep -qE '^_printk[[:space:]]' "$MODULE_DIR/modversions.tsv"

grep -qF 'gh_rm_get_vmid(rm, &self_vmid)' "$QCOM_SRC"
! grep -qF 'GH_QCOM_SCM' "$QCOM_SRC"
grep -qF '__free_page(nth_page(chunk->base, i));' "$BACKING_SRC"
! grep -qF 'free_contig_range(page_to_pfn(chunk->base), nr_pages)' "$BACKING_SRC"

CONFIG_FILE=""
for candidate in \
  "$KERNEL_ROOT/out/android14-6.1/common/.config" \
  "$KERNEL_ROOT/bazel-bin/common/kernel_aarch64/.config"; do
  [[ -s "$candidate" ]] || continue
  CONFIG_FILE="$candidate"
  break
done
if [[ -z "$CONFIG_FILE" ]]; then
  while IFS= read -r candidate; do
    grep -qx 'CONFIG_ARM64=y' "$candidate" 2>/dev/null || continue
    CONFIG_FILE="$candidate"; break
  done < <(find -L "$KERNEL_ROOT/bazel-bin/common" "$KERNEL_ROOT/out/android14-6.1" \
    -type f -name .config -print 2>/dev/null || true)
fi
[[ -n "$CONFIG_FILE" ]] || { echo '::error::Final config missing for module audit'; exit 1; }
grep -qx '# CONFIG_GUNYAH_QCOM_PLATFORM is not set' "$CONFIG_FILE" || {
  echo '::error::Final kernel config unexpectedly enables GUNYAH_QCOM_PLATFORM'; exit 1;
}

MODULE_SHA=$(awk '{print $1}' "$MODULE_DIR/gunyah_qcom.ko.sha256")
SCM_SHA=$(awk '{print $1}' "$MODULE_DIR/qcom-scm-build-only.ko.sha256")
cat >> "$REPORT_DIR/summary.md" <<EOF

## Patched e3q Gunyah Qualcomm module

- Module: \`gunyah_qcom.ko\`
- SHA-256: \`${MODULE_SHA}\`
- Build-only dependency qcom-scm SHA-256: \`${SCM_SHA}\`
- Kernel release: \`${EXPECTED_RELEASE}\`
- All 11 stock DZG1 gunyah_qcom import CRCs: exact
- New \`gh_rm_get_vmid\` import: present and KMI-listed
- Debug-only \`_printk\` import: absent
- Final \`CONFIG_GUNYAH_QCOM_PLATFORM\`: disabled (Samsung vendor_boot model retained)
- Contig teardown: per-page \`__free_page()\`; no \`free_contig_range()\` warning path
- Packaging: module is CI/live-test artifact only; AnyKernel and vendor_boot remain untouched
EOF

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  cat >> "$GITHUB_STEP_SUMMARY" <<EOF

### Patched e3q gunyah_qcom module
- SHA-256: \`${MODULE_SHA}\`
- 11/11 stock DZG1 import CRCs exact
- gh_rm_get_vmid: imported + KMI-listed
- _printk debug import: absent
- CONFIG_GUNYAH_QCOM_PLATFORM=n retained
- Saved inside Samsung DLKM CRC audit artifact for live ADB testing
EOF
fi

echo "Patched gunyah_qcom module audited: $MODULE (sha256=$MODULE_SHA)"
