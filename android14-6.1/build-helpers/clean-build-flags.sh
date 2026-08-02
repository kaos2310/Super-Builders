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

# Keep CONFIG_KSU_SUSFS_ENABLE_LOG compiled in while requiring the S928B daily
# default-off implementation. The dedicated helper also guards both jump-label
# transitions so repeated enable_log 0/1 calls cannot unbalance the static key.
SUSFS_SOURCE="./common/fs/susfs.c"
SUSFS_FRAGMENT="./common/arch/arm64/configs/sukisu_gki.fragment"

if [ -f "$SUSFS_FRAGMENT" ]; then
  grep -qx 'CONFIG_KSU_SUSFS_ENABLE_LOG=y' "$SUSFS_FRAGMENT" || {
    echo "::error::CONFIG_KSU_SUSFS_ENABLE_LOG must remain enabled"
    exit 1
  }
fi

if [ -f "$SUSFS_SOURCE" ]; then
  grep -qx 'DEFINE_STATIC_KEY_FALSE(susfs_is_log_enabled);' "$SUSFS_SOURCE" || {
    echo "::error::SUSFS logging static key must default to FALSE"
    exit 1
  }
  grep -qF 'if (!static_key_enabled(&susfs_is_log_enabled))' "$SUSFS_SOURCE" || {
    echo "::error::SUSFS logging enable transition is not guarded"
    exit 1
  }
  grep -qF 'if (static_key_enabled(&susfs_is_log_enabled))' "$SUSFS_SOURCE" || {
    echo "::error::SUSFS logging disable transition is not guarded"
    exit 1
  }
  grep -qF 'mutex_lock(&susfs_mutex_enable_log);' "$SUSFS_SOURCE" || {
    echo "::error::SUSFS logging transitions are not serialized"
    exit 1
  }
  grep -qF 'mutex_unlock(&susfs_mutex_enable_log);' "$SUSFS_SOURCE" || {
    echo "::error::SUSFS logging transition mutex is not released"
    exit 1
  }
fi

cd common
git config --global user.name "github-actions[bot]"
git config --global user.email "github-actions[bot]@users.noreply.github.com"
git add .
git commit -m "${SUFFIX}: Clean Build" || true
