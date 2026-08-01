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

# Keep CONFIG_KSU_SUSFS_ENABLE_LOG compiled in. Do not flip the upstream
# logging static key from TRUE to FALSE here: the SUSFS 2.2 runtime setter
# calls static_branch_disable() without checking the current state, so a
# default-FALSE key plus the normal `enable_log 0` boot configuration would
# unbalance the jump-label reference count. Logging is disabled safely by the
# runtime configuration installed by AnyKernel3 instead.
SUSFS_FRAGMENT="./common/arch/arm64/configs/sukisu_gki.fragment"

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
