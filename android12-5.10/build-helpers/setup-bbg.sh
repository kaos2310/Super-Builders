#!/bin/bash
set -euo pipefail

KERNEL_ROOT="${1:?}"
DEFCONFIG="${2:?}"

cd "$KERNEL_ROOT"
curl -LSs https://github.com/vc-teahouse/Baseband-guard/raw/main/setup.sh | bash
echo "CONFIG_BBG=y" >> "$DEFCONFIG"

# Determine the correct Kconfig path (Samsung kernels use kernel_platform/common)
KCONFIG_PATH="common/security/Kconfig"
if [ ! -f "$KCONFIG_PATH" ] && [ -f "kernel_platform/common/security/Kconfig" ]; then
  KCONFIG_PATH="kernel_platform/common/security/Kconfig"
fi

if [ ! -f "$KCONFIG_PATH" ]; then
  echo "Warning: Kconfig file not found at $KCONFIG_PATH"
  exit 1
fi

# lockdown is the LSM anchor on 5.10 kernels
sed -i '/^config LSM$/,/^help$/{ /^[[:space:]]*default/ { /baseband_guard/! s/lockdown/lockdown,baseband_guard/ } }' "$KCONFIG_PATH"
