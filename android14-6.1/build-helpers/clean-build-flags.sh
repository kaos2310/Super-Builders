#!/bin/bash
set -euo pipefail

KERNEL_ROOT="${1:?}"
KERNEL_VER="${2:?}"
SUFFIX="${3:-SukiSU}"

cd "$KERNEL_ROOT"

if [[ "$KERNEL_VER" == "5."* ]] || [[ "$KERNEL_VER" == "6.1" ]]; then
  perl -i -0777 -pe "s/(.*)echo \"\\\$res\"/\$1echo \"\\\$res-${SUFFIX}\"/s" ./common/scripts/setlocalversion
else
  perl -i -0777 -pe "s/(.*)echo \"\\\$\\{KERNELVERSION\\}\\\$\\{file_localversion\\}\\\$\\{config_localversion\\}\\\$\\{LOCALVERSION\\}\\\$\\{scm_version\\}\"/\$1echo \"\\\${KERNELVERSION}\\\${file_localversion}\\\${config_localversion}\\\${LOCALVERSION}-${SUFFIX}\\\${scm_version}\"/s" ./common/scripts/setlocalversion
fi

if [ -f "build/build.sh" ]; then
  sed -i 's/-dirty//' ./common/scripts/setlocalversion
else
  sed -i "/stable_scmversion_cmd/s/-maybe-dirty//g" ./build/kernel/kleaf/impl/stamp.bzl
  sed -i 's/-dirty//' ./common/scripts/setlocalversion
  rm -rf ./common/android/abi_gki_protected_exports_*
  perl -pi -e 's/^\s*"protected_exports_list"\s*:\s*"android\/abi_gki_protected_exports_aarch64",\s*$//;' ./common/BUILD.bazel
fi

# Keep CONFIG_KSU_SUSFS_ENABLE_LOG compiled in, but start each boot with
# logging disabled. susfs_set_log(bool enabled) remains untouched, so
# `ksu_susfs enable_log 1` and `ksu_susfs enable_log 0` continue to work.
SUSFS_SOURCE="./common/fs/susfs.c"
SUSFS_FRAGMENT="./common/arch/arm64/configs/sukisu_gki.fragment"

if [ -f "$SUSFS_SOURCE" ]; then
  python3 - "$SUSFS_SOURCE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
upstream = "bool susfs_is_log_enabled __read_mostly = true;"
default_off = "bool susfs_is_log_enabled __read_mostly = false;"

if upstream in text:
    text = text.replace(upstream, default_off, 1)
elif default_off not in text:
    raise SystemExit("SUSFS logging default declaration was not found")

required = (
    default_off,
    "void susfs_set_log(bool enabled)",
    "susfs_is_log_enabled = enabled;",
)
missing = [item for item in required if item not in text]
if missing:
    raise SystemExit(f"SUSFS runtime logging toggle verification failed: {missing}")

path.write_text(text, encoding="utf-8")
PY
fi

if [ -f "$SUSFS_FRAGMENT" ]; then
  grep -qx 'CONFIG_KSU_SUSFS_ENABLE_LOG=y' "$SUSFS_FRAGMENT" || {
    echo "::error::CONFIG_KSU_SUSFS_ENABLE_LOG must remain enabled"
    exit 1
  }
fi

cd common
git config --global user.name "github-actions[bot]"
git config --global user.email "github-actions[bot]@users.noreply.github.com"
git add .
git commit -m "${SUFFIX}: Clean Build" || true
