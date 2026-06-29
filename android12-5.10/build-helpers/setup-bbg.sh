#!/bin/bash
set -euo pipefail

KERNEL_ROOT="${1:?}"
DEFCONFIG="${2:?}"

cd "$KERNEL_ROOT"
curl -LSs https://github.com/vc-teahouse/Baseband-guard/raw/main/setup.sh | bash
echo "CONFIG_BBG=y" >> "$DEFCONFIG"

# Determine the correct Kconfig path
# Samsung kernels after cd "$KERNEL_ROOT" (which is kernel_platform/common) use: security/Kconfig
# Standard kernels use: common/security/Kconfig
KCONFIG_PATH="security/Kconfig"
if [ ! -f "$KCONFIG_PATH" ] && [ -f "common/security/Kconfig" ]; then
  KCONFIG_PATH="common/security/Kconfig"
fi

if [ ! -f "$KCONFIG_PATH" ]; then
  echo "Error: Kconfig file not found at $KCONFIG_PATH in $(pwd)"
  exit 1
fi

# lockdown is the LSM anchor on 5.10 kernels
sed -i '/^config LSM$/,/^help$/{ /^[[:space:]]*default/ { /baseband_guard/! s/lockdown/lockdown,baseband_guard/ } }' "$KCONFIG_PATH"
