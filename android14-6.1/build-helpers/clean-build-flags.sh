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

# Capture the exact module-version loader state after the workflow's
# "Apply Module Check Bypass" step and before the generated source commit.
# The report is copied into AnyKernel3, which the workflow already uploads.
AUDIT_ROOT="${GITHUB_WORKSPACE:-$KERNEL_ROOT}"
AUDIT_FILE="$AUDIT_ROOT/kmi-module-loader-audit.txt"
ARTIFACT_AUDIT="$AUDIT_ROOT/AnyKernel3/kmi-module-loader-audit.txt"

if [[ "$KERNEL_VER" == "6.1" || "$KERNEL_VER" == "6.6" || "$KERNEL_VER" == "6.12" ]]; then
  MODULE_VERSION_FILE="$KERNEL_ROOT/common/kernel/module/version.c"
else
  MODULE_VERSION_FILE="$KERNEL_ROOT/common/kernel/module.c"
fi

{
  echo "============================================================"
  echo "KMI MODULE LOADER SOURCE AUDIT"
  echo "============================================================"
  echo "UTC: $(date -u '+%Y-%m-%d %H:%M:%S')"
  echo "Kernel root: $KERNEL_ROOT"
  echo "Kernel version: $KERNEL_VER"
  echo "Workflow ref: ${GITHUB_REF:-unknown}"
  echo "Workflow SHA: ${GITHUB_SHA:-unknown}"
  echo "Module version file: $MODULE_VERSION_FILE"
  echo

  echo "============================================================"
  echo "1. RELEVANT SOURCE MATCHES"
  echo "============================================================"
  grep -RInE \
    'check_version|disagrees about version|try_to_force_load|IGNORE_MODVERSIONS|same_magic|modversions' \
    "$KERNEL_ROOT/common/kernel/module" 2>/dev/null || true
  echo

  echo "============================================================"
  echo "2. MODULE VERSION SOURCE"
  echo "============================================================"
  if [ -f "$MODULE_VERSION_FILE" ]; then
    sed -n '1,280p' "$MODULE_VERSION_FILE"
  else
    echo "[ERROR] Module version source not found"
  fi
  echo

  echo "============================================================"
  echo "3. BAD_VERSION CONTROL FLOW"
  echo "============================================================"
  if [ -f "$MODULE_VERSION_FILE" ]; then
    awk '
      /bad_version:/ { active=1; remaining=18 }
      active { print NR ":" $0; remaining-- }
      active && remaining <= 0 { active=0 }
    ' "$MODULE_VERSION_FILE"
  fi
  echo

  echo "============================================================"
  echo "4. UNCOMMITTED MODULE-LOADER DIFF"
  echo "============================================================"
  git -C "$KERNEL_ROOT/common" diff -- \
    kernel/module/version.c \
    kernel/module/main.c \
    kernel/module/internal.h \
    kernel/module.c 2>/dev/null || true
  echo

  echo "============================================================"
  echo "5. GIT IDENTITY AND HISTORY"
  echo "============================================================"
  git -C "$KERNEL_ROOT/common" log -1 \
    --format='commit=%H%nsubject=%s%nauthor=%an <%ae>%ndate=%ad' \
    --date=iso 2>/dev/null || true
  echo
  git -C "$KERNEL_ROOT/common" log --oneline -n 30 -- \
    kernel/module/version.c \
    kernel/module/main.c \
    kernel/module/internal.h \
    kernel/module.c 2>/dev/null || true
  echo

  echo "============================================================"
  echo "6. AUTOMATIC VERDICT"
  echo "============================================================"
  if [ -f "$MODULE_VERSION_FILE" ] && awk '
      /bad_version:/ { active=1; remaining=18; next }
      active && /return[[:space:]]+1[[:space:]]*;/ { found=1 }
      active { remaining-- }
      active && remaining <= 0 { active=0 }
      END { exit(found ? 0 : 1) }
    ' "$MODULE_VERSION_FILE"; then
    echo "[WARN] bad_version path returns success (return 1)."
    echo "[WARN] MODVERSIONS CRC mismatches are logged but accepted."
  else
    echo "[OK] No return-1 bypass found near bad_version."
  fi

  if grep -q 'CONFIG_MODULE_FORCE_LOAD=y' "$KERNEL_ROOT/common/arch/arm64/configs/sukisu_gki.fragment" 2>/dev/null; then
    echo "[WARN] CONFIG_MODULE_FORCE_LOAD is requested in the fragment."
  else
    echo "[INFO] CONFIG_MODULE_FORCE_LOAD is not requested in the fragment."
  fi

  echo "============================================================"
  echo "END"
  echo "============================================================"
} > "$AUDIT_FILE" 2>&1

cat "$AUDIT_FILE"
mkdir -p "$(dirname "$ARTIFACT_AUDIT")"
cp "$AUDIT_FILE" "$ARTIFACT_AUDIT"
echo "KMI audit saved to: $AUDIT_FILE"
echo "KMI audit included in AnyKernel artifact: $ARTIFACT_AUDIT"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "## KMI module-loader audit"
    echo
    echo "The post-bypass source audit is included as \`kmi-module-loader-audit.txt\` in the AnyKernel3 artifact."
    if grep -q '^\[WARN\] bad_version path returns success' "$AUDIT_FILE"; then
      echo
      echo "⚠️ The current workflow changes the \`bad_version\` path to return success, so CRC mismatches are accepted after being logged."
    fi
  } >> "$GITHUB_STEP_SUMMARY"
fi

cd common
git config --global user.name "github-actions[bot]"
git config --global user.email "github-actions[bot]@users.noreply.github.com"
git add .
git commit -m "${SUFFIX}: Clean Build" || true
