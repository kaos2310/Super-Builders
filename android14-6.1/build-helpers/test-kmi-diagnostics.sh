#!/bin/bash
set -euo pipefail

HELPERS_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION_DIR="$(cd "$HELPERS_DIR/.." && pwd)"
BASELINE="$VERSION_DIR/samsung-e3q-dlkm-crc-baseline.tsv"
AUDITOR="$HELPERS_DIR/verify-samsung-dlkm-crcs.sh"
COMPARATOR="$HELPERS_DIR/compare-kmi-variants.sh"
COLLECTOR="$HELPERS_DIR/collect-kmi-symtypes.sh"
CLEAN_FLAGS="$HELPERS_DIR/clean-build-flags.sh"
KASAN_STUB_HELPER="$HELPERS_DIR/apply-kasan-kmi-stub.sh"
DAILY_AUDIT="$HELPERS_DIR/audit-s928b-daily-config.sh"
BUILD_WORKFLOW="$VERSION_DIR/../.github/workflows/build-resukisu.yml"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

KERNEL_ROOT="$TMP_DIR/kernel"
SYMVERS_DIR="$KERNEL_ROOT/bazel-bin/common/kernel_aarch64"
VERSION_SOURCE="$KERNEL_ROOT/common/kernel/module/version.c"
mkdir -p "$SYMVERS_DIR" "$(dirname "$VERSION_SOURCE")"

awk '!/^#/ && NF >= 3 {
  print $3 "\t" $1 "\tvmlinux\tEXPORT_SYMBOL"
}' "$BASELINE" > "$SYMVERS_DIR/Module.symvers"

write_loader_policy() {
  local value="$1"
  cat > "$VERSION_SOURCE" <<EOF
static int check_version(void)
{
bad_version:
  pr_warn("disagrees about version of symbol");
  return $value;
}
EOF
}

write_loader_policy 0
mkdir -p "$SYMVERS_DIR/symtypes/kernel/module"
cat > "$SYMVERS_DIR/.config" <<'EOF'
CONFIG_ARM64=y
CONFIG_MODVERSIONS=y
EOF
cat > "$SYMVERS_DIR/symtypes/kernel/module/version.symtypes" <<'EOF'
check_version int check_version ( void )
EOF
git -C "$KERNEL_ROOT/common" init --quiet
git -C "$KERNEL_ROOT/common" config user.name test
git -C "$KERNEL_ROOT/common" config user.email test@example.invalid
git -C "$KERNEL_ROOT/common" add .
git -C "$KERNEL_ROOT/common" commit --quiet -m fixture

"$AUDITOR" "$KERNEL_ROOT" "$BASELINE" "$TMP_DIR/symtypes" symtypes full
grep -qx 'EXACT_COUNT=1679' "$TMP_DIR/symtypes/summary.env"
grep -qx 'REFERENCE_COUNT=795' "$TMP_DIR/symtypes/summary.env"
grep -qx 'VARIANT_COUNT=0' "$TMP_DIR/symtypes/summary.env"
grep -qx 'MISSING_COUNT=0' "$TMP_DIR/symtypes/summary.env"
"$COLLECTOR" "$KERNEL_ROOT" "$TMP_DIR/symtypes" full symtypes
grep -qx 'SYMTYPES_COUNT=1' "$TMP_DIR/symtypes/summary.env"
tar -tzf "$TMP_DIR/symtypes/symtypes.tar.gz" | grep -qx \
  'bazel-bin/common/kernel_aarch64/symtypes/kernel/module/version.symtypes'

if "$AUDITOR" "$KERNEL_ROOT" "$BASELINE" "$TMP_DIR/strict" strict full-strict; then
  echo "Strict audit unexpectedly accepted 795 CRC differences" >&2
  exit 1
fi

write_loader_policy 1
"$AUDITOR" "$KERNEL_ROOT" "$BASELINE" "$TMP_DIR/runtime" runtime-compat full

awk 'BEGIN { changed=0 }
  !changed && $2 == "___pskb_trim" { $1="0xdeadbeef"; changed=1 }
  { print }
' OFS='\t' "$SYMVERS_DIR/Module.symvers" > "$SYMVERS_DIR/Module.symvers.new"
mv "$SYMVERS_DIR/Module.symvers.new" "$SYMVERS_DIR/Module.symvers"

write_loader_policy 0
"$AUDITOR" "$KERNEL_ROOT" "$BASELINE" "$TMP_DIR/variant" symtypes gki-control
grep -qx 'VARIANT_COUNT=1' "$TMP_DIR/variant/summary.env"

if "$AUDITOR" "$KERNEL_ROOT" "$BASELINE" "$TMP_DIR/runtime-mutated" runtime-compat full; then
  echo "Runtime audit unexpectedly accepted an unpinned build CRC" >&2
  exit 1
fi

mkdir -p "$TMP_DIR/artifacts/gki" "$TMP_DIR/artifacts/full"
cp "$TMP_DIR/variant/summary.env" "$TMP_DIR/variant/Module.symvers" "$TMP_DIR/artifacts/gki/"
cp "$TMP_DIR/symtypes/summary.env" "$TMP_DIR/symtypes/Module.symvers" "$TMP_DIR/artifacts/full/"
"$COMPARATOR" "$BASELINE" "$TMP_DIR/artifacts" "$TMP_DIR/comparison"
grep -q $'^gki-control\t1679\t794\t1\t0\tno\t' "$TMP_DIR/comparison/variant-summary.tsv"
grep -q $'^full\t1679\t795\t0\t0\tno\t' "$TMP_DIR/comparison/variant-summary.tsv"

test_strict_daily_config() {
  local config="$TMP_DIR/strict-daily.config"

  awk '
    /^REQUIRED=\(/ { in_required=1; next }
    in_required && /^\)/ { in_required=0; next }
    in_required {
      for (field=1; field<=NF; field++) {
        if ($field ~ /^CONFIG_[A-Z0-9_]+$/) print $field "=y"
      }
    }
  ' "$DAILY_AUDIT" > "$config"
  cat >> "$config" <<'EOF'
# CONFIG_CGROUP_PIDS is not set
# CONFIG_LRU_GEN_STATS is not set
CONFIG_LOG_BUF_SHIFT=22
CONFIG_IP6_NF_NAT=y
# CONFIG_KFENCE is not set
# CONFIG_KASAN is not set
# CONFIG_UBSAN is not set
EOF

  "$DAILY_AUDIT" "$config" false false strict
  if "$DAILY_AUDIT" "$config" false false runtime-compat; then
    echo "Runtime-compatible audit unexpectedly accepted strict-disabled features" >&2
    exit 1
  fi
}

test_strict_daily_config

test_kleaf_kmi_flags() {
  grep -qF 'BAZEL_FLAGS+=(--nokmi_symbol_list_strict_mode --nokmi_symbol_list_violations_check)' \
    "$BUILD_WORKFLOW"
  if grep -qF 'BAZEL_FLAGS+=(--kmi_symbol_list_strict_mode' "$BUILD_WORKFLOW"; then
    echo "Strict workflow uses a positive Kleaf flag unsupported by the pinned wrapper" >&2
    exit 1
  fi
  grep -qF '"$CONFIG_TOOL" --file "$DEFCONFIG_FRAGMENT" --enable "$SYMBOL"' "$BUILD_WORKFLOW"
  grep -qF '"$CONFIG_TOOL" --file "$DEFCONFIG" --undefine "$SYMBOL"' "$BUILD_WORKFLOW"
  grep -qF 'grep -qx "CONFIG_${SYMBOL}=y" "$DEFCONFIG_FRAGMENT"' "$BUILD_WORKFLOW"
}

test_kleaf_kmi_flags

test_strict_anykernel_gate() {
  grep -qF 'package_strict_anykernel:' "$BUILD_WORKFLOW"
  grep -qF 'Strict AnyKernel packaging requires kmi_mode=strict' "$BUILD_WORKFLOW"
  grep -qF 'Strict AnyKernel packaging is restricted to kmi_profile=full-strict' "$BUILD_WORKFLOW"
  grep -qF 'Strict AnyKernel packaging is restricted to device_codename=e3q' "$BUILD_WORKFLOW"
  grep -qF 'test "$SAMSUNG_DLKM_EXACT_COUNT" = "2474"' "$BUILD_WORKFLOW"
  grep -qF 'test "$SAMSUNG_DLKM_COMPATIBLE_COUNT" = "0"' "$BUILD_WORKFLOW"
  grep -qF 'test "$SAMSUNG_DLKM_UNEXPECTED_COUNT" = "0"' "$BUILD_WORKFLOW"
  grep -qF 'test "$SAMSUNG_DLKM_MISSING_COUNT" = "0"' "$BUILD_WORKFLOW"
  grep -qF 'test "$SAMSUNG_DLKM_RUNTIME_FALLBACK" = "strict-rejection"' "$BUILD_WORKFLOW"
  grep -qF 'Upload exact flashable Strict KMI ZIP' "$BUILD_WORKFLOW"
}

test_strict_anykernel_gate

test_kasan_kmi_layout() {
  local fixture="$TMP_DIR/kasan-kmi-layout"
  mkdir -p "$fixture/mm/kasan" "$fixture/include/linux"

  cat > "$fixture/mm/Makefile" <<'EOF'
obj-$(CONFIG_KASAN) += kasan/
EOF
  cat > "$fixture/mm/kasan/hw_tags.c" <<'EOF'
DEFINE_STATIC_KEY_FALSE(kasan_flag_enabled);
EXPORT_SYMBOL(kasan_flag_enabled);
EOF
  cat > "$fixture/include/linux/kasan.h" <<'EOF'
#ifdef CONFIG_KASAN
struct kasan_cache {
	bool is_kmalloc;
};
#else /* CONFIG_KASAN */

static inline void kasan_unpoison_range(const void *address, size_t size) {}
#endif /* CONFIG_KASAN */
EOF
  cat > "$fixture/include/linux/slub_def.h" <<'EOF'
struct kmem_cache {
#ifdef CONFIG_KASAN
	struct kasan_cache kasan_info;
#endif
	unsigned int useroffset;
};
EOF

  "$KASAN_STUB_HELPER" "$fixture"
  "$KASAN_STUB_HELPER" "$fixture"
  grep -qxF 'obj-y += kasan_kmi_compat.o' "$fixture/mm/Makefile"
  [[ "$(grep -cF 'Samsung KMI: retain the HW-tags kasan_cache layout with KASAN off.' \
      "$fixture/include/linux/kasan.h")" -eq 1 ]]
  [[ "$(grep -cF 'Samsung KMI: layout only; KASAN instrumentation remains disabled.' \
      "$fixture/include/linux/slub_def.h")" -eq 1 ]]
  [[ "$(grep -c $'^\tstruct kasan_cache kasan_info;$' \
      "$fixture/include/linux/slub_def.h")" -eq 1 ]]
}

test_kasan_kmi_layout

test_clean_flags_mode() {
  local mode="$1"
  local expected_return="$2"
  local fixture="$TMP_DIR/clean-$mode"
  mkdir -p \
    "$fixture/common/scripts" \
    "$fixture/common/kernel/module" \
    "$fixture/common/arch/arm64/configs" \
    "$fixture/build/kernel/kleaf/impl"

  cat > "$fixture/common/scripts/setlocalversion" <<'EOF'
#!/bin/sh
res=test
echo "$res"
EOF
  cat > "$fixture/build/kernel/kleaf/impl/stamp.bzl" <<'EOF'
stable_scmversion_cmd = "-maybe-dirty"
EOF
  cat > "$fixture/common/BUILD.bazel" <<'EOF'
kernel_build(
    name = "kernel_aarch64",
    "protected_exports_list": "android/abi_gki_protected_exports_aarch64",
)
EOF
  cat > "$fixture/common/kernel/module/version.c" <<'EOF'
static int check_version(void)
{
bad_version:
  pr_warn("disagrees about version of symbol");
  return 0;
}
EOF
  cat > "$fixture/common/kernel/module/main.c" <<'EOF'
if (blacklisted(info->name)) {
  err = -EPERM;
  goto free_copy;
}
EOF
  cat > "$fixture/common/arch/arm64/configs/sukisu_gki.fragment" <<'EOF'
CONFIG_KSU=y
EOF

  git -C "$fixture/common" init --quiet
  git -C "$fixture/common" config user.name test
  git -C "$fixture/common" config user.email test@example.invalid
  git -C "$fixture/common" add .
  git -C "$fixture/common" commit --quiet -m fixture

  GITHUB_WORKSPACE="$fixture/audit" "$CLEAN_FLAGS" "$fixture" 6.1 ReSukiSU "$mode"
  awk -v expected="$expected_return" '
    /bad_version:/ { active=1; next }
    active && /return[[:space:]]+[01];/ {
      exit($0 ~ ("return[[:space:]]+" expected ";") ? 0 : 1)
    }
    END { if (!active) exit 1 }
  ' "$fixture/common/kernel/module/version.c"
  ! grep -q 'protected_exports_list' "$fixture/common/BUILD.bazel"
}

test_clean_flags_mode symtypes 0
test_clean_flags_mode strict 0
test_clean_flags_mode runtime-compat 1

echo "KMI diagnostics self-test passed."
