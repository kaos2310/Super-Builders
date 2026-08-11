#!/bin/bash
set -euo pipefail

ADB_BIN="${ADB:-adb}"
REPORT_DIR="${1:-zeromount-susfs-runtime-audit}"
mkdir -p "$REPORT_DIR"

adb_root() {
  "$ADB_BIN" shell su -c "$1" | tr -d '\r'
}

"$ADB_BIN" wait-for-device
ROOT_ID=$(adb_root id)
grep -q 'uid=0(root)' <<< "$ROOT_ID" || {
  echo "::error::ADB root through KernelSU is unavailable"
  exit 1
}

{
  printf 'root=%s\n' "$ROOT_ID"
  printf 'model=%s\n' "$("$ADB_BIN" shell getprop ro.product.model | tr -d '\r')"
  printf 'pda=%s\n' "$("$ADB_BIN" shell getprop ro.build.PDA | tr -d '\r')"
  printf 'csc=%s\n' "$("$ADB_BIN" shell getprop ro.boot.sales_code | tr -d '\r')"
  printf 'kernel=%s\n' "$(adb_root 'uname -a')"
  printf 'boot_id=%s\n' "$(adb_root 'cat /proc/sys/kernel/random/boot_id')"
  printf 'boot_completed=%s\n' "$("$ADB_BIN" shell getprop sys.boot_completed | tr -d '\r')"
} > "$REPORT_DIR/device.env"

grep -qx 'pda=S928BXXS6DZG1' "$REPORT_DIR/device.env" || {
  echo "::error::Connected device is not running S928BXXS6DZG1"
  cat "$REPORT_DIR/device.env"
  exit 1
}
grep -qx 'boot_completed=1' "$REPORT_DIR/device.env" || {
  echo "::error::Android boot is not complete"
  exit 1
}

adb_root 'zm status' > "$REPORT_DIR/zeromount-status.txt"
adb_root 'zm detect' > "$REPORT_DIR/zeromount-detect.txt"
adb_root 'zm vfs query-status' > "$REPORT_DIR/zeromount-vfs-status.txt"
adb_root 'zm vfs list' > "$REPORT_DIR/zeromount-vfs-rules.txt"
adb_root 'cat /data/adb/zeromount/.status.json' > "$REPORT_DIR/zeromount-status.json"
adb_root 'cat /data/adb/zeromount/config.toml' > "$REPORT_DIR/zeromount-config.toml"

grep -qiE 'engine([_: ]+)(active|true)' "$REPORT_DIR/zeromount-status.txt" || {
  echo "::error::ZeroMount engine is not active"
  exit 1
}
grep -qiE 'rules:[[:space:]]*[1-9][0-9]*' "$REPORT_DIR/zeromount-vfs-status.txt" || {
  echo "::error::ZeroMount VFS has no active rules"
  exit 1
}
grep -qiE 'SUSFS[^0-9]*v?2\.2\.0|v2\.2\.0' "$REPORT_DIR/zeromount-detect.txt" || {
  echo "::error::ZeroMount did not detect SUSFS v2.2.0"
  exit 1
}
for feature in kstat path maps kstat_redirect; do
  grep -qiE "${feature}([_: ]+)(true|yes|enabled)" "$REPORT_DIR/zeromount-detect.txt" || {
    echo "::error::ZeroMount did not confirm SUSFS ${feature} support"
    exit 1
  }
done
grep -qx 'hide_sus_mounts = false' "$REPORT_DIR/zeromount-config.toml" || {
  echo "::error::Droidspaces requires ZeroMount hide_sus_mounts=false"
  exit 1
}

python3 - "$REPORT_DIR/zeromount-status.json" <<'PY'
import json
from pathlib import Path
import sys

data = json.loads(Path(sys.argv[1]).read_text())

def values(node, key):
    found = []
    if isinstance(node, dict):
        for current, value in node.items():
            if current == key:
                found.append(value)
            found.extend(values(value, key))
    elif isinstance(node, list):
        for value in node:
            found.extend(values(value, key))
    return found

def require_value(key, expected):
    observed = values(data, key)
    if expected not in observed:
        raise SystemExit(f"ZeroMount status lacks {key}={expected!r}; observed={observed!r}")

require_value("engine_active", True)
require_value("degraded", False)
failed = values(data, "failed") + values(data, "rules_failed")
if failed and any(value != 0 for value in failed if isinstance(value, int)):
    raise SystemExit(f"ZeroMount reports failed rules: {failed!r}")
applied = values(data, "applied") + values(data, "rules_applied")
if not any(isinstance(value, int) and value > 0 for value in applied):
    raise SystemExit(f"ZeroMount reports no applied rules: {applied!r}")
PY

adb_root 'ksu_susfs show version' > "$REPORT_DIR/susfs-version.txt"
adb_root 'ksu_susfs show variant' > "$REPORT_DIR/susfs-variant.txt"
adb_root 'ksu_susfs show enabled_features' > "$REPORT_DIR/susfs-enabled-features.txt"
grep -q 'v2.2.0' "$REPORT_DIR/susfs-version.txt"
grep -qi 'GKI' "$REPORT_DIR/susfs-variant.txt"

SUSFS_FEATURES=(
  CONFIG_KSU_SUSFS_SUS_PATH
  CONFIG_KSU_SUSFS_SUS_MOUNT
  CONFIG_KSU_SUSFS_SUS_KSTAT
  CONFIG_KSU_SUSFS_SUS_KSTAT_REDIRECT
  CONFIG_KSU_SUSFS_SUS_MAP
  CONFIG_KSU_SUSFS_OPEN_REDIRECT
  CONFIG_KSU_SUSFS_UNICODE_FILTER
  CONFIG_KSU_SUSFS_SPOOF_UNAME
  CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
  CONFIG_KSU_SUSFS_ENABLE_LOG
)
for feature in "${SUSFS_FEATURES[@]}"; do
  grep -qx "$feature" "$REPORT_DIR/susfs-enabled-features.txt" || {
    echo "::error::SUSFS runtime feature is missing: $feature"
    exit 1
  }
done

adb_root 'test -x /system/bin/droidspaces && /system/bin/droidspaces --version 2>&1 || true' \
  > "$REPORT_DIR/droidspaces.txt"
grep -qi 'droidspaces' "$REPORT_DIR/droidspaces.txt" || {
  echo "::error::Droidspaces ZeroMount injection is not executable"
  exit 1
}

adb_root 'sha256sum /data/adb/modules/droidspaces/system/bin/droidspaces /system/bin/droidspaces' \
  > "$REPORT_DIR/droidspaces-sha256.txt"
[[ "$(awk '{print $1}' "$REPORT_DIR/droidspaces-sha256.txt" | sort -u | wc -l)" -eq 1 ]] || {
  echo "::error::Droidspaces injected target differs from its module source"
  exit 1
}

cat > "$REPORT_DIR/summary.md" <<EOF
# S928BXXS6DZG1 ZeroMount/SUSFS runtime audit

- KernelSU root: verified
- Android boot: complete
- ZeroMount VFS engine: active with non-zero rules and no reported failures
- ZeroMount/SUSFS bridge: path, kstat, maps and kstat redirect detected
- SUSFS: v2.2.0 GKI with every required compiled feature available
- Droidspaces: executable ZeroMount injection with matching source/target SHA-256
- Safety profile: global SUS mount hiding remains disabled for Droidspaces
EOF

cat "$REPORT_DIR/summary.md"
