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

# Keep SUSFS logging compiled in, default-off, serialized and safely toggleable.
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

if [[ "$KERNEL_VER" == "6.1" || "$KERNEL_VER" == "6.6" || "$KERNEL_VER" == "6.12" ]]; then
  MODULE_VERSION_FILE="$KERNEL_ROOT/common/kernel/module/version.c"
else
  MODULE_VERSION_FILE="$KERNEL_ROOT/common/kernel/module.c"
fi
MODULE_MAIN_FILE="$KERNEL_ROOT/common/kernel/module/main.c"

# Runtime recovery for Samsung vendor/DLKM modules:
# keep the mismatch warning, but accept a CRC mismatch. The preceding workflow
# step already applies this mode; enforce and audit it here so a later patch
# cannot silently restore strict rejection and reproduce the S928B bootloop.
python3 - "$MODULE_VERSION_FILE" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
if not path.is_file():
    raise SystemExit(f"module version source not found: {path}")

text = path.read_text()
pattern = re.compile(r"(bad_version:.*?\breturn\s+)[01](\s*;)", re.S)
text, count = pattern.subn(r"\g<1>1\2", text, count=1)
if count != 1:
    raise SystemExit(f"unexpected bad_version replacement count: {count}")

match = re.search(r"bad_version:(.*?)(?:\n[}\t ]*\n|\Z)", text, re.S)
if not match:
    raise SystemExit("bad_version block not found")
block = match.group(1)
if not re.search(r"\breturn\s+1\s*;", block):
    raise SystemExit("bad_version does not accept logged CRC mismatches")
if re.search(r"\breturn\s+0\s*;", block):
    raise SystemExit("bad_version still rejects CRC mismatches")
if "disagrees about version of symbol" not in block:
    raise SystemExit("CRC mismatch warning was removed")

path.write_text(text)
PY

# A real module blacklist match must still fail with -EPERM.
if [ -f "$MODULE_MAIN_FILE" ]; then
  sed -i -E 's|^([[:space:]]*)//[[:space:]]*err = -EPERM;|\1err = -EPERM;|' "$MODULE_MAIN_FILE"
  BLACKLIST_BLOCK=$(sed -n '/if (blacklisted(info->name))/,/goto free_copy;/p' "$MODULE_MAIN_FILE")
  printf '%s\n' "$BLACKLIST_BLOCK"
  grep -Eq '^[[:space:]]*err = -EPERM;' <<< "$BLACKLIST_BLOCK" || {
    echo "::error::Blacklisted modules must return -EPERM"
    exit 1
  }
  if grep -Eq '^[[:space:]]*//[[:space:]]*err = -EPERM;' <<< "$BLACKLIST_BLOCK"; then
    echo "::error::Commented blacklist errno remains"
    exit 1
  fi
fi

# Never hide patch failures behind an earlier `|| true`.
mapfile -t PATCH_REJECTS < <(find "$KERNEL_ROOT" -type f -name '*.rej' -print)
if [ "${#PATCH_REJECTS[@]}" -gt 0 ]; then
  printf '::error::Patch reject found: %s\n' "${PATCH_REJECTS[@]}"
  exit 1
fi

AUDIT_ROOT="${GITHUB_WORKSPACE:-$KERNEL_ROOT}"
mkdir -p "$AUDIT_ROOT"
AUDIT_FILE="$AUDIT_ROOT/kmi-module-loader-audit.txt"

{
  echo "============================================================"
  echo "KMI MODULE LOADER RUNTIME-COMPAT AUDIT"
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
  echo "2. BAD_VERSION CONTROL FLOW"
  echo "============================================================"
  awk '
    /bad_version:/ { active=1; remaining=18 }
    active { print NR ":" $0; remaining-- }
    active && remaining <= 0 { active=0 }
  ' "$MODULE_VERSION_FILE"
  echo

  echo "============================================================"
  echo "3. MODULE-LOADER DIFF"
  echo "============================================================"
  git -C "$KERNEL_ROOT/common" diff -- \
    kernel/module/version.c \
    kernel/module/main.c \
    kernel/module/internal.h \
    kernel/module.c 2>/dev/null || true
  echo

  echo "============================================================"
  echo "4. AUTOMATIC VERDICT"
  echo "============================================================"
  if awk '
      /bad_version:/ { active=1; remaining=18; next }
      active && /return[[:space:]]+1[[:space:]]*;/ { accept=1 }
      active && /return[[:space:]]+0[[:space:]]*;/ { reject=1 }
      active { remaining-- }
      active && remaining <= 0 { active=0 }
      END { exit(accept && !reject ? 0 : 1) }
    ' "$MODULE_VERSION_FILE"; then
    echo "[OK] CRC mismatches are logged and accepted for Samsung KMI compatibility."
  else
    echo "[ERROR] bad_version is not in runtime-compat mode."
    exit 1
  fi

  if grep -qF 'disagrees about version of symbol' "$MODULE_VERSION_FILE"; then
    echo "[OK] CRC mismatch diagnostics remain enabled."
  else
    echo "[ERROR] CRC mismatch diagnostics are missing."
    exit 1
  fi

  if [ -f "$MODULE_MAIN_FILE" ] && sed -n '/if (blacklisted(info->name))/,/goto free_copy;/p' "$MODULE_MAIN_FILE" | grep -Eq '^[[:space:]]*err = -EPERM;'; then
    echo "[OK] Blacklisted modules still return -EPERM."
  else
    echo "[ERROR] Module blacklist errno propagation is invalid."
    exit 1
  fi

  if grep -q 'CONFIG_MODULE_FORCE_LOAD=y' "$SUSFS_FRAGMENT" 2>/dev/null; then
    echo "[WARN] CONFIG_MODULE_FORCE_LOAD is requested in the fragment."
  else
    echo "[OK] CONFIG_MODULE_FORCE_LOAD is not requested in the fragment."
  fi

  echo "============================================================"
  echo "END"
  echo "============================================================"
} > "$AUDIT_FILE" 2>&1

cat "$AUDIT_FILE"
echo "KMI runtime-compat audit saved outside AnyKernel3: $AUDIT_FILE"

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  {
    echo "## KMI module-loader runtime compatibility"
    echo
    echo "- ✅ CRC mismatches remain visible in dmesg but are accepted to preserve Samsung DLKM boot compatibility."
    echo "- ✅ Real module blacklist matches still propagate \`-EPERM\`."
    echo "- ✅ No patch reject files were found before compilation."
  } >> "$GITHUB_STEP_SUMMARY"
fi

cd common
git config --global user.name "github-actions[bot]"
git config --global user.email "github-actions[bot]@users.noreply.github.com"
git add .
git commit -m "${SUFFIX}: Clean Build" || true
