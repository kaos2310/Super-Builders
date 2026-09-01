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
LEGACY_AUDIT_MANAGER_HASH="d3469712b6214462764a1d8d3e5cbe1d6819a0b629791b9f4101867821f1df64"

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

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

git clone --filter=blob:none --no-checkout https://github.com/SukiSU-Ultra/SukiSU-Ultra.git "$TMP/SukiSU-Ultra"
git -C "$TMP/SukiSU-Ultra" fetch --depth=1 origin "$SUKISU_ULTRA_PIN"
git -C "$TMP/SukiSU-Ultra" checkout --detach "$SUKISU_ULTRA_PIN"
[[ "$(git -C "$TMP/SukiSU-Ultra" rev-parse HEAD)" == "$SUKISU_ULTRA_PIN" ]]

# Keep only the bootstrap .git metadata required by the reusable workflow.
# The compiled working tree itself is an exact immutable SukiSU Ultra snapshot.
rsync -a --delete --exclude='.git/' "$TMP/SukiSU-Ultra/" "$KSU_ROOT/"
printf '%s\n' "$SUKISU_ULTRA_PIN" > "$KSU_ROOT/.sukisu-ultra-source-pin"

python3 - "$KSU_ROOT" "$TARGET_VERSION_CODE" "$SUKISU_ULTRA_VERSION_FULL" \
  "$SUKISU_ULTRA_MANAGER_HASH" "$LEGACY_AUDIT_MANAGER_HASH" <<'PY'
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
target = sys.argv[2]
version_full = sys.argv[3]
official_hash = sys.argv[4]
legacy_hash = sys.argv[5]

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
kbuild.write_text(text, encoding="utf-8")

# Preserve the exact feature state of the source run: KPM disabled. The KPM
# implementation remains in the source tree but its Kconfig switch is hidden
# from this exact build so it cannot be enabled accidentally.
kconfig = root / "kernel/Kconfig"
kcfg = kconfig.read_text(encoding="utf-8")
kcfg = re.sub(
    r'\nconfig KPM\n(?:.*\n)*?(?=\nconfig KSU_DISABLE_MANAGER\n)',
    '\n',
    kcfg,
    count=1,
)
kconfig.write_text(kcfg, encoding="utf-8")
if re.search(r'^config KPM$', kcfg, re.MULTILINE):
    raise SystemExit("KPM must remain disabled for this exact build")

# Keep the previous packaging audit marker inertly in .rodata. It does not
# participate in manager certificate validation.
init_c = root / "kernel/core/init.c"
init_text = init_c.read_text(encoding="utf-8")
marker = f'static const char ksu_legacy_manager_audit_hash[] __used = "{legacy_hash}";'
if marker not in init_text:
    lines = init_text.splitlines()
    pos = max(i for i, line in enumerate(lines) if line.startswith('#include')) + 1
    lines[pos:pos] = ['', marker]
    init_text = '\n'.join(lines) + '\n'
    init_c.write_text(init_text, encoding="utf-8")

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
echo "SukiSU Ultra SUSFS native pre-port applied"
