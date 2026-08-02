#!/bin/bash
set -euo pipefail

CONFIG_FILE="${1:?final kernel config}"
REQUIRE_KPM="${2:-true}"
REQUIRE_CUSTOM_MANAGER="${3:-false}"
[[ -f "$CONFIG_FILE" ]] || {
  echo "::error::Kernel config not found: $CONFIG_FILE"
  exit 1
}

REQUIRED=(
  CONFIG_KSU
  CONFIG_KSU_MULTI_MANAGER_SUPPORT
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
  CONFIG_TCP_CONG_BBR3
  CONFIG_DEFAULT_BBR3
  CONFIG_NET_SCH_FQ
  CONFIG_NET_SCH_FQ_CODEL
  CONFIG_NET_SCH_CAKE
  CONFIG_NET_SCH_PIE
  CONFIG_NET_SCH_FQ_PIE
  CONFIG_NTSYNC
  CONFIG_IP_SET
  CONFIG_NETFILTER_XT_SET
  CONFIG_IP6_NF_TARGET_MASQUERADE
  CONFIG_IP_NF_TARGET_TTL
  CONFIG_IP6_NF_TARGET_HL
  CONFIG_IP6_NF_MATCH_HL
  CONFIG_ZRAM
  CONFIG_ZRAM_WRITEBACK
  CONFIG_CRYPTO_LZ4K
  CONFIG_CRYPTO_LZ4KD
  CONFIG_ZRAM_DEF_COMP_LZ4KD
  CONFIG_LRU_GEN
  CONFIG_LRU_GEN_STATS
  CONFIG_CFI_CLANG
  CONFIG_SHADOW_CALL_STACK
  CONFIG_RANDOMIZE_KSTACK_OFFSET
  CONFIG_RANDOMIZE_KSTACK_OFFSET_DEFAULT
  CONFIG_UNMAP_KERNEL_AT_EL0
  CONFIG_VIRTUALIZATION
  CONFIG_KVM
  CONFIG_KASAN
  CONFIG_KASAN_HW_TAGS
)
if [[ "$REQUIRE_KPM" == "true" ]]; then
  REQUIRED+=(CONFIG_KPM)
fi
missing=()
for symbol in "${REQUIRED[@]}"; do
  grep -qx "${symbol}=y" "$CONFIG_FILE" || missing+=("$symbol")
done
if ((${#missing[@]})); then
  printf '::error::Required S928B daily options missing: %s\n' "${missing[*]}"
  exit 1
fi

# IPv6_NAT_FIX deliberately rewrites only the embedded IKCONFIG copy from y to
# n. The final build .config is checked strictly before packaging.
grep -Eq '^CONFIG_IP6_NF_NAT=(y|n)  grep -qx "# CONFIG_${symbol} is not set" "$CONFIG_FILE" || {
    echo "::error::CONFIG_${symbol} is active or absent from the final config"
    exit 1
  }
done

for symbol in KASAN_GENERIC KASAN_SW_TAGS; do
  grep -qx "# CONFIG_${symbol} is not set" "$CONFIG_FILE" || {
    echo "::error::CONFIG_${symbol} must stay disabled in the HW-tags fallback"
    exit 1
  }
done

if grep -Eq '^CONFIG_(KFENCE|KASAN_GENERIC|KASAN_SW_TAGS|UBSAN(_TRAP|_BOUNDS|_LOCAL_BOUNDS)?)=y$' "$CONFIG_FILE"; then
  echo "::error::Final kernel config still enables a daily-build sanitizer"
  grep -E '^CONFIG_(KFENCE|KASAN|UBSAN)' "$CONFIG_FILE" || true
  exit 1
fi

echo "Verified ${#REQUIRED[@]} S928B daily features in $CONFIG_FILE"
echo "Verified CONFIG_KFENCE=n and CONFIG_UBSAN=n"
echo "Verified GKI KMI fallback CONFIG_KASAN=y and CONFIG_KASAN_HW_TAGS=y"
echo "Verified CONFIG_CFI_CLANG=y and CONFIG_SHADOW_CALL_STACK=y"
echo "Verified KStack offset randomization is enabled by default"
echo "Verified KVM is compiled; /dev/kvm additionally requires EL2/HYP from the bootloader"
 "$CONFIG_FILE" || {
  echo "::error::CONFIG_IP6_NF_NAT is absent from the final or embedded config"
  exit 1
}

for symbol in KFENCE UBSAN; do
  grep -qx "# CONFIG_${symbol} is not set" "$CONFIG_FILE" || {
    echo "::error::CONFIG_${symbol} is active or absent from the final config"
    exit 1
  }
done

for symbol in KASAN_GENERIC KASAN_SW_TAGS; do
  grep -qx "# CONFIG_${symbol} is not set" "$CONFIG_FILE" || {
    echo "::error::CONFIG_${symbol} must stay disabled in the HW-tags fallback"
    exit 1
  }
done

if grep -Eq '^CONFIG_(KFENCE|KASAN_GENERIC|KASAN_SW_TAGS|UBSAN(_TRAP|_BOUNDS|_LOCAL_BOUNDS)?)=y$' "$CONFIG_FILE"; then
  echo "::error::Final kernel config still enables a daily-build sanitizer"
  grep -E '^CONFIG_(KFENCE|KASAN|UBSAN)' "$CONFIG_FILE" || true
  exit 1
fi

echo "Verified ${#REQUIRED[@]} S928B daily features in $CONFIG_FILE"
echo "Verified CONFIG_KFENCE=n and CONFIG_UBSAN=n"
echo "Verified GKI KMI fallback CONFIG_KASAN=y and CONFIG_KASAN_HW_TAGS=y"
echo "Verified CONFIG_CFI_CLANG=y and CONFIG_SHADOW_CALL_STACK=y"
echo "Verified KStack offset randomization is enabled by default"
echo "Verified KVM is compiled; /dev/kvm additionally requires EL2/HYP from the bootloader"
