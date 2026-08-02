#!/bin/bash
set -euo pipefail

CONFIG_FILE="${1:?final kernel config}"
[[ -f "$CONFIG_FILE" ]] || {
  echo "::error::Kernel config not found: $CONFIG_FILE"
  exit 1
}

REQUIRED=(
  CONFIG_KSU
  CONFIG_KSU_SUSFS
  CONFIG_KSU_SUSFS_SUS_PATH
  CONFIG_KSU_SUSFS_SUS_MOUNT
  CONFIG_KSU_SUSFS_SUS_KSTAT
  CONFIG_KSU_SUSFS_SUS_KSTAT_REDIRECT
  CONFIG_KSU_SUSFS_SUS_MAP
  CONFIG_KSU_SUSFS_OPEN_REDIRECT
  CONFIG_KSU_SUSFS_UNICODE_FILTER
  CONFIG_KSU_SUSFS_HIDDEN_NAME
  CONFIG_KSU_SUSFS_SPOOF_UNAME
  CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
  CONFIG_KSU_SUSFS_ENABLE_LOG
  CONFIG_ZEROMOUNT
  CONFIG_KPM
  CONFIG_BBG
  CONFIG_NAMESPACES
  CONFIG_UTS_NS
  CONFIG_IPC_NS
  CONFIG_PID_NS
  CONFIG_NET_NS
  CONFIG_USER_NS
  CONFIG_CGROUP_PIDS
  CONFIG_ANDROID_BINDERFS
  CONFIG_SYSVIPC
  CONFIG_POSIX_MQUEUE
  CONFIG_TCP_CONG_BBR
  CONFIG_NET_SCH_FQ
  CONFIG_ZRAM
  CONFIG_ZRAM_WRITEBACK
  CONFIG_CRYPTO_LZ4K
  CONFIG_CRYPTO_LZ4KD
  CONFIG_ZRAM_DEF_COMP_LZ4KD
  CONFIG_LRU_GEN
  CONFIG_LRU_GEN_STATS
  CONFIG_CFI_CLANG
  CONFIG_SHADOW_CALL_STACK
)

missing=()
for symbol in "${REQUIRED[@]}"; do
  grep -qx "${symbol}=y" "$CONFIG_FILE" || missing+=("$symbol")
done
if ((${#missing[@]})); then
  printf '::error::Required S928B daily options missing: %s\n' "${missing[*]}"
  exit 1
fi

for symbol in KFENCE KASAN UBSAN; do
  grep -qx "# CONFIG_${symbol} is not set" "$CONFIG_FILE" || {
    echo "::error::CONFIG_${symbol} is active or absent from the final config"
    exit 1
  }
done

if grep -Eq '^CONFIG_(KFENCE|KASAN(_GENERIC|_SW_TAGS|_HW_TAGS)?|UBSAN(_TRAP|_BOUNDS|_LOCAL_BOUNDS)?)=y$' "$CONFIG_FILE"; then
  echo "::error::Final kernel config still enables a daily-build sanitizer"
  grep -E '^CONFIG_(KFENCE|KASAN|UBSAN)' "$CONFIG_FILE" || true
  exit 1
fi

echo "Verified ${#REQUIRED[@]} S928B daily features in $CONFIG_FILE"
echo "Verified CONFIG_KFENCE=n, CONFIG_KASAN=n and CONFIG_UBSAN=n"
echo "Verified CONFIG_CFI_CLANG=y and CONFIG_SHADOW_CALL_STACK=y"
