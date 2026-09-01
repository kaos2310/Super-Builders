#!/bin/bash
set -euo pipefail

KSU_ROOT="${1:?KernelSU source directory}"
EXPECTED_BRANCH="${2:?expected bootstrap branch}"
EXPECTED_COMMIT="${3:?expected bootstrap commit}"
TARGET_VERSION_CODE="${4:?target version code}"
MANAGER_CERT_SIZE="${5:-}"
MANAGER_CERT_HASH="${6:-}"

SUKISU_ULTRA_PIN="9fbe8fe8ca90c62c259c5894bf96d02ac31209b9"
SUKISU_ULTRA_TAG="v4.2.0"
SUKISU_ULTRA_VERSION_CODE="40901"
SUKISU_ULTRA_VERSION_FULL="v4.2.0-9fbe8fe8@main"
SUKISU_ULTRA_MANAGER_HASH="947ae944f3de4ed4c21a7e4f7953ecf351bfa2b36239da37a34111ad29993eef"

[[ "$TARGET_VERSION_CODE" == "$SUKISU_ULTRA_VERSION_CODE" ]] || {
  echo "::error::This exact S928B workflow is pinned to SukiSU Ultra $SUKISU_ULTRA_VERSION_CODE"
  exit 1
}

BOOTSTRAP_HEAD=$(git -C "$KSU_ROOT" rev-parse HEAD)
[[ "$BOOTSTRAP_HEAD" == "$EXPECTED_COMMIT" ]] || {
  echo "::error::Bootstrap pin mismatch: expected $EXPECTED_COMMIT, got $BOOTSTRAP_HEAD"
  exit 1
}

BRANCH_REF="refs/remotes/origin/$EXPECTED_BRANCH"
git -C "$KSU_ROOT" show-ref --verify --quiet "$BRANCH_REF" || {
  echo "::error::Bootstrap branch ref is missing: $BRANCH_REF"
  exit 1
}

# This helper is invoked once during source setup and again by the strict build
# identity gate. The second invocation must be read-only: replacing the working
# tree again would erase the SUSFS/ZeroMount port that was deliberately applied
# between those two calls. When the exact immutable SukiSU source marker and
# release identity are already present, validate them and preserve the tree.
MARKER="$KSU_ROOT/.sukisu-ultra-source-pin"
if [[ -f "$MARKER" && "$(tr -d '[:space:]' < "$MARKER")" == "$SUKISU_ULTRA_PIN" ]]; then
  grep -Eq "^KSU_VERSION[[:space:]]*:=[[:space:]]*$SUKISU_ULTRA_VERSION_CODE$" "$KSU_ROOT/kernel/Kbuild" || {
    echo "::error::Existing SukiSU tree lost KSU_VERSION=$SUKISU_ULTRA_VERSION_CODE"
    exit 1
  }
  grep -Fqx "KSU_VERSION_FULL := $SUKISU_ULTRA_VERSION_FULL" "$KSU_ROOT/kernel/Kbuild" || {
    echo "::error::Existing SukiSU tree lost KSU_VERSION_FULL=$SUKISU_ULTRA_VERSION_FULL"
    exit 1
  }
  grep -Fq "$SUKISU_ULTRA_MANAGER_HASH" "$KSU_ROOT/kernel/Kbuild" || {
    echo "::error::Existing SukiSU tree lost the official manager certificate hash"
    exit 1
  }
  if grep -Eq '^KSU_EXPECTED_(SIZE|HASH)2[[:space:]]*:=' "$KSU_ROOT/kernel/Kbuild"; then
    echo "::error::SukiSU production build contains a secondary/PR manager signature"
    exit 1
  fi
  grep -Rqx 'config KPM' "$KSU_ROOT" --include='Kconfig*' || {
    echo "::error::Existing SukiSU tree lost the KPM Kconfig symbol"
    exit 1
  }
  [[ -f "$KSU_ROOT/kernel/supercall/dispatch.c" ]] || {
    echo "::error::Existing SukiSU dispatcher is missing"
    exit 1
  }
  git -C "$KSU_ROOT" tag -f "$SUKISU_ULTRA_TAG" "$EXPECTED_COMMIT" >/dev/null
  echo "SukiSU Ultra $SUKISU_ULTRA_VERSION_CODE source already configured; preserving post-setup SUSFS/ZeroMount integration"
  echo "SukiSU Ultra compiled source: $SUKISU_ULTRA_PIN"
  echo "SukiSU Ultra version code: $SUKISU_ULTRA_VERSION_CODE"
  echo "SukiSU Ultra version full: $SUKISU_ULTRA_VERSION_FULL"
  echo "SukiSU Ultra manager hash: $SUKISU_ULTRA_MANAGER_HASH"
  echo "SukiSU Ultra manager policy: official production signature only"
  echo "SukiSU Ultra KPM source: present"
  exit 0
fi

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

git clone --filter=blob:none --no-checkout https://github.com/SukiSU-Ultra/SukiSU-Ultra.git "$TMP/SukiSU-Ultra"
git -C "$TMP/SukiSU-Ultra" fetch --depth=1 origin "$SUKISU_ULTRA_PIN"
git -C "$TMP/SukiSU-Ultra" checkout --detach "$SUKISU_ULTRA_PIN"
[[ "$(git -C "$TMP/SukiSU-Ultra" rev-parse HEAD)" == "$SUKISU_ULTRA_PIN" ]]

# Keep only the bootstrap .git metadata required by the reusable workflow.
# The compiled working tree itself is an exact immutable SukiSU Ultra snapshot.
rsync -a --delete --exclude='.git/' "$TMP/SukiSU-Ultra/" "$KSU_ROOT/"
printf '%s\n' "$SUKISU_ULTRA_PIN" > "$MARKER"

python3 - "$KSU_ROOT" "$TARGET_VERSION_CODE" "$SUKISU_ULTRA_VERSION_FULL" \
  "$SUKISU_ULTRA_MANAGER_HASH" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
target = sys.argv[2]
version_full = sys.argv[3]
official_hash = sys.argv[4]

kbuild = root / "kernel/Kbuild"
text = kbuild.read_text(encoding="utf-8")
text, n = re.subn(
    r'^KSU_VERSION\s*:=\s*\$\(if \$\(LOCAL_COUNT\),\$\(shell expr \$\(VERSION_BASE\) \+ \$\(LOCAL_COUNT\) - \$\(VERSION_OFFSET\)\),13000\)$',
    f'KSU_VERSION     := {target}',
    text,
    count=1,
    flags=re.MULTILINE,
)
if n != 1 and not re.search(rf'^KSU_VERSION\s*:=\s*{re.escape(target)}$', text, re.MULTILINE):
    raise SystemExit("Cannot freeze SukiSU Ultra KSU_VERSION")

text, n = re.subn(
    r'^KSU_VERSION_FULL\s*:=.*$',
    f'KSU_VERSION_FULL := {version_full}',
    text,
    count=1,
    flags=re.MULTILINE,
)
if n != 1 and f'KSU_VERSION_FULL := {version_full}' not in text:
    raise SystemExit("Cannot freeze SukiSU Ultra KSU_VERSION_FULL")

if official_hash not in text:
    raise SystemExit("Official SukiSU Ultra manager hash missing from Kbuild")

# SukiSU exposes KSU_EXPECTED_SIZE2/HASH2 for PR testing. Defining that slot
# deliberately sets KSU_GET_INFO_FLAG_PR_BUILD and makes the manager reject the
# kernel as a production build. Release artifacts must use only the official
# SukiSU manager certificate above.
if re.search(r'^KSU_EXPECTED_(?:SIZE|HASH)2\s*:=', text, re.MULTILINE):
    raise SystemExit("SukiSU production build contains a secondary/PR manager signature")
kbuild.write_text(text, encoding="utf-8")

# Preserve SukiSU Ultra 40901's upstream KPM implementation. Actual KPM
# enablement is controlled by the reusable workflow's --kpm defconfig flag and
# is verified later by the strict identity/config gate as CONFIG_KPM=y.
kconfig = root / "kernel/Kconfig"
kcfg = kconfig.read_text(encoding="utf-8")
if not re.search(r'^config KPM$', kcfg, re.MULTILINE):
    raise SystemExit("SukiSU Ultra 40901 KPM Kconfig symbol is missing")

# SukiSU 40901 has two reset_avc_cache() call sites. Anchor the SUSFS SID
# refresh specifically to apply_kernelsu_rules() so the generic pre-port helper
# does not need an ambiguous text match and the initial KSU policy install
# always refreshes the SUSFS SID cache.
rules = root / "kernel/selinux/rules.c"
rules_text = rules.read_text(encoding="utf-8")
if "    susfs_set_batch_sid();\n" not in rules_text:
    anchor = "    reset_avc_cache();\nout_unlock:\n"
    replacement = (
        "    reset_avc_cache();\n"
        "#ifdef CONFIG_KSU_SUSFS\n"
        "    susfs_set_batch_sid();\n"
        "#endif\n"
        "out_unlock:\n"
    )
    if rules_text.count(anchor) != 1:
        raise SystemExit(f"Cannot locate unique apply_kernelsu_rules SUSFS SID anchor: {rules_text.count(anchor)}")
    rules.write_text(rules_text.replace(anchor, replacement, 1), encoding="utf-8")
PY

PREPARE="$GITHUB_WORKSPACE/android14-6.1/build-helpers/prepare-sukisu-40901-susfs-port.sh"
chmod +x "$PREPARE"
"$PREPARE" "$KSU_ROOT"

# The surrounding legacy label plumbing uses git-describe on the bootstrap
# metadata. Tag that immutable bootstrap commit with the actual compiled release
# label; the compiled source SHA is independently enforced by the source marker.
git -C "$KSU_ROOT" tag -f "$SUKISU_ULTRA_TAG" "$EXPECTED_COMMIT" >/dev/null

echo "SukiSU Ultra compiled source: $SUKISU_ULTRA_PIN"
echo "SukiSU Ultra version code: $SUKISU_ULTRA_VERSION_CODE"
echo "SukiSU Ultra version full: $SUKISU_ULTRA_VERSION_FULL"
echo "SukiSU Ultra manager hash: $SUKISU_ULTRA_MANAGER_HASH"
echo "SukiSU Ultra manager policy: official production signature only"
echo "SukiSU Ultra KPM source: present"
echo "SukiSU Ultra SUSFS native pre-port applied"
