#!/usr/bin/env python3
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".github/workflows/build-resukisu.yml"
DST = ROOT / ".github/workflows/build-sukisu-v420.yml"
RUN = ROOT / ".github/workflows/run-resukisu-35057-strict.yml"
PIN_FILE = ROOT / "android14-6.1/sukisu-pin.txt"

SUKISU_PIN = "9fbe8fe8ca90c62c259c5894bf96d02ac31209b9"
SUKISU_TAG = "v4.2.0"
SUKISU_MANAGER_HASH = "947ae944f3de4ed4c21a7e4f7953ecf351bfa2b36239da37a34111ad29993eef"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, repl: str, label: str) -> str:
    out, count = re.subn(pattern, repl, text, count=1, flags=re.S)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return out


text = SRC.read_text(encoding="utf-8")

text = replace_once(text, "name: Build ReSukiSU\n", "name: Build SukiSU Ultra v4.2.0\n", "workflow name")
text = replace_once(
    text,
    'description: "Use only the minimum ReSukiSU config for CRC attribution"',
    'description: "Use only the minimum SukiSU Ultra config for CRC attribution"',
    "minimal config description",
)
text = replace_once(
    text,
    'name: "ReSukiSU ${{ inputs.kernel_version }}.${{ inputs.sub_level }}"',
    'name: "SukiSU Ultra v4.2.0 ${{ inputs.kernel_version }}.${{ inputs.sub_level }}"',
    "job name",
)

# ReSukiSU-only release inputs are not part of the SukiSU Ultra build API.
text = regex_once(
    text,
    r'''      resukisu_source_branch:\n        type: string\n        default: "dev"\n      resukisu_version_code:\n        type: string\n        default: "35116"\n      resukisu_expected_size:\n        type: string\n        default: ""\n      resukisu_expected_hash:\n        type: string\n        default: ""\n''',
    "",
    "remove ReSukiSU-only workflow inputs",
)

text = regex_once(
    text,
    r'''      KSU_VARIANT: ReSukiSU\n      KSU_DIR: KernelSU\n      RESUKISU_VERSION_CODE: \$\{\{ inputs\.resukisu_version_code \}\}\n      RESUKISU_VERSION_LABEL: \$\{\{ inputs\.resukisu_version_code \}\}\n      RESUKISU_VERSION_FULL: ReSukiSU-\$\{\{ inputs\.resukisu_version_code \}\}\n''',
    '''      KSU_VARIANT: SukiSU\n      KSU_DIR: KernelSU\n      SUKISU_RELEASE_TAG: v4.2.0\n      SUKISU_VERSION_CODE: "auto"\n      SUKISU_VERSION_LABEL: v4.2.0\n      SUKISU_VERSION_FULL: v4.2.0\n''',
    "variant environment",
)

text = replace_once(
    text,
    'ARTIFACT_BASE="${KERNEL_VER}.${SUBLEVEL}-${ANDROID_VER}-${OS_PATCH}-ReSukiSU-${RESUKISU_VERSION_LABEL}"',
    'ARTIFACT_BASE="${KERNEL_VER}.${SUBLEVEL}-${ANDROID_VER}-${OS_PATCH}-SukiSU-Ultra-v4.2.0"',
    "artifact base",
)

setup_block = r'''    - name: Setup SukiSU Ultra v4.2.0
      working-directory: ${{ env.KERNEL_ROOT }}
      env:
        SUKISU_COMMIT: ${{ inputs.sukisu_commit }}
      run: |
        set -euo pipefail
        PIN="${SUKISU_COMMIT:-$(tr -d '[:space:]' < "$GITHUB_WORKSPACE/$VERSION_DIR/sukisu-pin.txt" 2>/dev/null || true)}"
        [ -n "$PIN" ] || { echo "::error::SukiSU Ultra commit pin is required"; exit 1; }
        [ "$PIN" = "9fbe8fe8ca90c62c259c5894bf96d02ac31209b9" ] || {
          echo "::error::This workflow is locked to SukiSU Ultra v4.2.0 ($PIN)"
          exit 1
        }

        curl -LSs "https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/${PIN}/kernel/setup.sh" | bash -s builtin
        [ -d "$KERNEL_ROOT/$KSU_DIR" ] || { echo "FATAL: $KSU_DIR not created by setup.sh"; exit 1; }

        cd "$KERNEL_ROOT/$KSU_DIR"
        git fetch --depth=1 origin "$PIN"
        git checkout --detach FETCH_HEAD
        ACTUAL_PIN=$(git rev-parse HEAD)
        [ "$ACTUAL_PIN" = "$PIN" ] || {
          echo "::error::SukiSU Ultra pin mismatch: expected $PIN, got $ACTUAL_PIN"
          exit 1
        }

        # v4.2.0 derives KSU_VERSION from the repository commit count. Fetch
        # enough history to make that value deterministic at the release pin,
        # then freeze both numeric and semantic identities in Kbuild.
        git fetch --unshallow origin 2>/dev/null || true
        git fetch --no-tags origin main:refs/remotes/origin/main 2>/dev/null || true
        COMMIT_COUNT=$(git rev-list --count "$PIN")
        if [ "$COMMIT_COUNT" -le 2815 ]; then
          echo "::error::SukiSU history is still shallow (commit count $COMMIT_COUNT)"
          exit 1
        fi
        VERSION_CODE=$((40000 + COMMIT_COUNT - 2815))
        VERSION_FULL="v4.2.0-${VERSION_CODE}"

        python3 - "$KERNEL_ROOT/$KSU_DIR/kernel/Kbuild" "$VERSION_CODE" "$VERSION_FULL" <<'PY'
        from pathlib import Path
        import re
        import sys

        path = Path(sys.argv[1])
        version_code, version_full = sys.argv[2:]
        data = path.read_text(encoding="utf-8")
        data, n_code = re.subn(
            r'^KSU_VERSION\s*:=.*$',
            f'KSU_VERSION := {version_code}',
            data,
            count=1,
            flags=re.MULTILINE,
        )
        data, n_full = re.subn(
            r'^KSU_VERSION_FULL\s*:=.*$',
            f'KSU_VERSION_FULL := {version_full}',
            data,
            count=1,
            flags=re.MULTILINE,
        )
        if n_code != 1 or n_full != 1:
            raise SystemExit(f"Unable to freeze SukiSU version fields in {path}")
        path.write_text(data, encoding="utf-8")
        PY

        grep -qx "KSU_VERSION := ${VERSION_CODE}" kernel/Kbuild
        grep -qx "KSU_VERSION_FULL := ${VERSION_FULL}" kernel/Kbuild
        grep -qx 'config KPM' kernel/Kconfig
        grep -qF 'obj-$(CONFIG_KPM) += kpm/kpm.o' kernel/Kbuild
        grep -qF 'obj-$(CONFIG_KPM) += kpm/super_access.o' kernel/Kbuild

        {
          echo "SUKISU_VERSION_CODE=$VERSION_CODE"
          echo "SUKISU_VERSION_LABEL=$VERSION_FULL"
          echo "SUKISU_VERSION_FULL=$VERSION_FULL"
          echo "SUKISU_COMMIT=$ACTUAL_PIN"
        } >> "$GITHUB_ENV"
        echo "Pinned SukiSU Ultra ${VERSION_FULL} to ${ACTUAL_PIN}"

        cd "$KERNEL_ROOT/common"
        SUPERCALLS="drivers/kernelsu/supercalls.c"
        if [ -f "$SUPERCALLS" ]; then
          sed -i '/ksu_mark_running_process/d' "$SUPERCALLS"
          if grep -q "vzalloc" "$SUPERCALLS" && ! head -5 "$SUPERCALLS" | grep -q "vmalloc.h"; then
            sed -i '1a #include <linux/vmalloc.h>' "$SUPERCALLS"
          fi
        fi
'''

text = regex_once(
    text,
    r'''    - name: Setup ReSukiSU\n.*?(?=\n    - name: Fix Old Kernel Compatibility)''',
    setup_block.rstrip("\n"),
    "SukiSU setup block",
)

verify_block = r'''    - name: Verify SukiSU Ultra v4.2.0 + KPM build identity
      if: inputs.device_codename == 'e3q'
      env:
        EXPECTED_PIN: ${{ inputs.sukisu_commit }}
        ADD_KPM: ${{ inputs.add_kpm }}
        ADD_SUSFS: ${{ inputs.add_susfs }}
        ADD_ZEROMOUNT: ${{ inputs.add_zeromount }}
      run: |
        set -euo pipefail
        test "$KSU_VARIANT" = "SukiSU"
        PIN="${EXPECTED_PIN:-$(tr -d '[:space:]' < "$GITHUB_WORKSPACE/$VERSION_DIR/sukisu-pin.txt")}"
        test "$PIN" = "9fbe8fe8ca90c62c259c5894bf96d02ac31209b9"
        test "$(git -C "$KERNEL_ROOT/$KSU_DIR" rev-parse HEAD)" = "$PIN"
        grep -qx 'config KPM' "$KERNEL_ROOT/$KSU_DIR/kernel/Kconfig"
        grep -qF 'obj-$(CONFIG_KPM) += kpm/kpm.o' "$KERNEL_ROOT/$KSU_DIR/kernel/Kbuild"
        grep -qF 'obj-$(CONFIG_KPM) += kpm/super_access.o' "$KERNEL_ROOT/$KSU_DIR/kernel/Kbuild"

        if [[ "$ADD_SUSFS" == "true" ]]; then
          test "${SUSFS_EXPECTED_VERSION:-}" = "v2.3.0"
          test "${SUSFS_PINNED_COMMIT:-}" = "5727f79e3a7175cfb0e1a754fc2ed78eaf866237"
          grep -qxF '#define SUSFS_VERSION "v2.3.0"' "$KERNEL_ROOT/common/include/linux/susfs.h"
        fi
        if [[ "$ADD_ZEROMOUNT" == "true" ]]; then
          grep -qx 'CONFIG_ZEROMOUNT=y' "$DEFCONFIG_FRAGMENT"
          test -f "$KERNEL_ROOT/common/fs/zeromount.c"
        fi
        if [[ "$ADD_KPM" == "true" ]]; then
          grep -qx 'CONFIG_KPM=y' "$DEFCONFIG_FRAGMENT" || {
            echo "::error::KPM requested but CONFIG_KPM=y is missing"
            exit 1
          }
        else
          echo "::error::This S24 Ultra SukiSU v4.2.0 strict build requires KPM"
          exit 1
        fi

        echo "SukiSU Ultra: ${SUKISU_VERSION_FULL}"
        echo "SUKISU_VERSION_CODE=${SUKISU_VERSION_CODE}"
        echo "SUKISU_COMMIT=$PIN"
        echo "KPM=enabled"
        if [[ "$ADD_SUSFS" == "true" ]]; then
          echo "SUSFS_VERSION=${SUSFS_EXPECTED_VERSION}"
          echo "SUSFS_COMMIT=${SUSFS_PINNED_COMMIT}"
        fi
'''

text = regex_once(
    text,
    r'''    - name: Verify ReSukiSU build identity\n.*?(?=\n    - name: Clean Module Lists)''',
    verify_block.rstrip("\n"),
    "SukiSU identity verification",
)

text = replace_once(
    text,
    'bash "$HELPERS/clean-build-flags.sh" . "$KERNEL_VER" "ReSukiSU" "${{ inputs.kmi_mode }}"',
    'bash "$HELPERS/clean-build-flags.sh" . "$KERNEL_VER" "SukiSU" "${{ inputs.kmi_mode }}"',
    "clean build flags variant",
)

# SukiSU v4.2.0 uses its official manager certificate from Kbuild.
text = text.replace("REQUIRE_CUSTOM_MANAGER: ${{ inputs.resukisu_expected_hash != '' }}", "REQUIRE_CUSTOM_MANAGER: false")
text = text.replace("EXPECTED_MANAGER_HASH: ${{ inputs.resukisu_expected_hash }}", 'EXPECTED_MANAGER_HASH: ""')
text = replace_once(
    text,
    "grep -aF 'd3469712b6214462764a1d8d3e5cbe1d6819a0b629791b9f4101867821f1df64' \"$ANYKERNEL3/Image\" >/dev/null || {\n          echo \"::error::Official ReSukiSU manager certificate hash is missing from the kernel image\"",
    f"grep -aF '{SUKISU_MANAGER_HASH}' \"$ANYKERNEL3/Image\" >/dev/null || {{\n          echo \"::error::Official SukiSU Ultra manager certificate hash is missing from the kernel image\"",
    "manager certificate audit",
)

text = replace_once(
    text,
    "        ReSukiSU: ${RESUKISU_VERSION_FULL}",
    "        SukiSU Ultra: ${SUKISU_VERSION_FULL}",
    "strict KMI manifest identity",
)
text = replace_once(text, 'echo "## ReSukiSU | ${KERNEL_VER}.${SUBLEVEL}"', 'echo "## SukiSU Ultra v4.2.0 + KPM | ${KERNEL_VER}.${SUBLEVEL}"', "job summary")

# Fail closed if any functional ReSukiSU release plumbing survived the port.
for forbidden in (
    "Setup ReSukiSU",
    "Verify ReSukiSU",
    "ReSukiSU/ReSukiSU",
    "configure-resukisu-release.sh",
    "RESUKISU_VERSION_",
    "resukisu-pin.txt",
    "inputs.resukisu_",
):
    if forbidden in text:
        raise SystemExit(f"Generated workflow still contains forbidden ReSukiSU plumbing: {forbidden}")

if "add_kpm:" not in text or '[[ "$ADD_KPM" == "true" ]] && ASSEMBLE_FLAGS="$ASSEMBLE_FLAGS --kpm"' not in text:
    raise SystemExit("Generated workflow lost the KPM input or --kpm assembly path")
if "SUSFS_EXPECTED_VERSION" not in text:
    raise SystemExit("Generated workflow lost pinned SUSFS integration")
if "GUNYAH_ADAPTIVE_BACKING" not in text:
    raise SystemExit("Generated workflow lost the Gunyah adaptive backing path")

DST.write_text(text, encoding="utf-8")
PIN_FILE.write_text(SUKISU_PIN + "\n", encoding="utf-8")

run = RUN.read_text(encoding="utf-8")
run = replace_once(run, "name: S928B ZZHL ReSukiSU 35116 Gunyah RM-Append Build", "name: S928B ZZHL SukiSU Ultra v4.2.0 KPM Gunyah RM-Append Build", "run workflow name")
run = replace_once(run, 'run-name: "S928BXXU6ZZHL EUX — ReSukiSU 35116 + Gunyah RM MEM_APPEND / SCM-VMID"', 'run-name: "S928BXXU6ZZHL EUX — SukiSU Ultra v4.2.0 + KPM + SUSFS 2.3.0 + Gunyah RM MEM_APPEND / SCM-VMID"', "run display name")
run = replace_once(run, "      - agent/resukisu-35115-eux-zzhl", "      - agent/sukisu-ultra-v4.2.0-susfs-2.3.0", "run branch")
run = replace_once(run, "      - '.github/workflows/build-resukisu.yml'", "      - '.github/workflows/build-sukisu-v420.yml'", "run build path")
run = replace_once(run, "      - 'android14-6.1/resukisu-pin.txt'", "      - 'android14-6.1/sukisu-pin.txt'", "run pin path")
run = replace_once(run, "  group: s928b-resukisu-35116-exact-strict-${{ github.ref_name }}", "  group: s928b-sukisu-v420-kpm-exact-strict-${{ github.ref_name }}", "concurrency group")
run = replace_once(run, "    name: Full strict KMI gate / ReSukiSU 6.1.162 / Gunyah RM MEM_APPEND + SCM-VMID", "    name: Full strict KMI gate / SukiSU Ultra v4.2.0 + KPM / 6.1.162 / Gunyah RM MEM_APPEND + SCM-VMID", "strict gate name")
run = replace_once(run, "    uses: ./.github/workflows/build-resukisu.yml", "    uses: ./.github/workflows/build-sukisu-v420.yml", "reusable workflow")
run = replace_once(run, "      add_kpm: false", "      add_kpm: true", "KPM enable")
run = replace_once(run, "      sukisu_commit: f7829ddf548a18b851d653feb76b4a569b8fd2a4\n      resukisu_source_branch: main\n      resukisu_version_code: \"35116\"", f"      sukisu_commit: {SUKISU_PIN}", "SukiSU pin inputs")

for required in (
    "SukiSU Ultra v4.2.0",
    "add_kpm: true",
    f"sukisu_commit: {SUKISU_PIN}",
    "build-sukisu-v420.yml",
    "agent/sukisu-ultra-v4.2.0-susfs-2.3.0",
):
    if required not in run:
        raise SystemExit(f"Run workflow migration is missing: {required}")

RUN.write_text(run, encoding="utf-8")
print(f"Generated {DST.relative_to(ROOT)}")
print(f"Updated {RUN.relative_to(ROOT)}")
print(f"Pinned SukiSU Ultra {SUKISU_TAG} to {SUKISU_PIN}")
print("KPM is mandatory for the generated strict build")
