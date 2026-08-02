#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common tree}"
FRAGMENT="${2:?final defconfig fragment}"
DEFCONFIG="${3:?base defconfig}"
MODE="${4:-kleaf}"
CONFIG_TOOL="$COMMON_TREE/scripts/config"

[[ -x "$CONFIG_TOOL" ]] || {
  echo "::error::Kernel config editor is unavailable: $CONFIG_TOOL"
  exit 1
}
[[ -f "$FRAGMENT" ]] || {
  echo "::error::Final defconfig fragment is unavailable: $FRAGMENT"
  exit 1
}

DISABLED=(
  KFENCE
  KASAN_GENERIC KASAN_SW_TAGS
  UBSAN UBSAN_TRAP UBSAN_BOUNDS UBSAN_LOCAL_BOUNDS
)

# android14-6.1 GKI symbol lists require the kasan_flag_enabled export. Keep
# only HW-tag KASAN compiled for KMI compatibility; AnyKernel3 forces kasan=off
# so the sanitizer remains inactive on the daily kernel.
REQUIRED_KASAN=(KASAN KASAN_HW_TAGS)
REQUIRED_HARDENING=(
  RANDOMIZE_KSTACK_OFFSET RANDOMIZE_KSTACK_OFFSET_DEFAULT
  UNMAP_KERNEL_AT_EL0 VIRTUALIZATION KVM
)

# Kleaf applies this fragment after the base GKI defconfig and olddefconfig.
# Legacy build.sh additionally consumes the edited base defconfig.
TARGETS=("$FRAGMENT")
if [[ "$MODE" == "legacy" ]]; then
  [[ -f "$DEFCONFIG" ]] || {
    echo "::error::Legacy base defconfig is unavailable: $DEFCONFIG"
    exit 1
  }
  TARGETS+=("$DEFCONFIG")
fi

for target in "${TARGETS[@]}"; do
  for symbol in "${DISABLED[@]}"; do
    "$CONFIG_TOOL" --file "$target" --disable "$symbol"
  done
  for symbol in "${REQUIRED_KASAN[@]}"; do
    "$CONFIG_TOOL" --file "$target" --enable "$symbol"
  done
  for symbol in "${REQUIRED_HARDENING[@]}"; do
    "$CONFIG_TOOL" --file "$target" --enable "$symbol"
  done

  for symbol in "${DISABLED[@]}"; do
    grep -qx "# CONFIG_${symbol} is not set" "$target" || {
      echo "::error::CONFIG_${symbol} was not disabled in $target"
      exit 1
    }
  done
  for symbol in "${REQUIRED_KASAN[@]}"; do
    grep -qx "CONFIG_${symbol}=y" "$target" || {
      echo "::error::CONFIG_${symbol} was not enabled in $target"
      exit 1
    }
  done
  for symbol in "${REQUIRED_HARDENING[@]}"; do
    grep -qx "CONFIG_${symbol}=y" "$target" || {
      echo "::error::CONFIG_${symbol} was not enabled in $target"
      exit 1
    }
  done
done

echo "S928B daily debug sanitizers disabled in the final build input:"
printf '  CONFIG_%s=n\n' "${DISABLED[@]}"
echo "S928B GKI KMI compatibility retained; AnyKernel3 must force kasan=off:"
printf '  CONFIG_%s=y\n' "${REQUIRED_KASAN[@]}"
echo "S928B hardening and kernel-side virtualization support retained:"
printf '  CONFIG_%s=y\n' "${REQUIRED_HARDENING[@]}"
echo "Note: functional /dev/kvm still requires an EL2/HYP handoff from the bootloader."
