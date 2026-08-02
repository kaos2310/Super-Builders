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
  KASAN KASAN_GENERIC KASAN_SW_TAGS KASAN_HW_TAGS
  UBSAN UBSAN_TRAP UBSAN_BOUNDS UBSAN_LOCAL_BOUNDS
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

  for symbol in "${DISABLED[@]}"; do
    grep -qx "# CONFIG_${symbol} is not set" "$target" || {
      echo "::error::CONFIG_${symbol} was not disabled in $target"
      exit 1
    }
  done
done

echo "S928B daily sanitizers disabled in the final build input:"
printf '  CONFIG_%s=n\n' "${DISABLED[@]}"
