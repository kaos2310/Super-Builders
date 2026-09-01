#!/bin/bash
set -euo pipefail

KSU_ROOT="${1:?SukiSU Ultra source directory}"
EXPECTED_BRANCH="${2:?expected SukiSU Ultra branch}"
EXPECTED_COMMIT="${3:?expected SukiSU Ultra commit}"
TARGET_VERSION_CODE="${4:?target SukiSU Ultra version code}"
MANAGER_CERT_SIZE="${5:-}"
MANAGER_CERT_HASH="${6:-}"
PYTHON_BIN="${PYTHON3:-python3}"

[[ "$TARGET_VERSION_CODE" =~ ^[0-9]+$ ]] || {
  echo "::error::Invalid SukiSU Ultra version code: $TARGET_VERSION_CODE"
  exit 1
}

ACTUAL_COMMIT=$(git -C "$KSU_ROOT" rev-parse HEAD)
[[ "$ACTUAL_COMMIT" == "$EXPECTED_COMMIT" ]] || {
  echo "::error::SukiSU Ultra pin mismatch: expected $EXPECTED_COMMIT, got $ACTUAL_COMMIT"
  exit 1
}

BRANCH_REF="refs/remotes/origin/$EXPECTED_BRANCH"
git -C "$KSU_ROOT" show-ref --verify --quiet "$BRANCH_REF" || {
  echo "::error::SukiSU Ultra branch ref is missing: $BRANCH_REF"
  exit 1
}
git -C "$KSU_ROOT" merge-base --is-ancestor "$EXPECTED_COMMIT" "$BRANCH_REF" || {
  echo "::error::SukiSU Ultra commit $EXPECTED_COMMIT is not on origin/$EXPECTED_BRANCH"
  exit 1
}

# The upstream Kbuild deliberately consults the live GitHub commit count. For a
# reproducible kernel build that is pinned to an immutable commit, freeze the
# numeric kernel version to the requested value instead of allowing a later
# upstream commit to change KSU_VERSION while this source SHA stays unchanged.
"$PYTHON_BIN" - "$KSU_ROOT" "$TARGET_VERSION_CODE" "$MANAGER_CERT_SIZE" "$MANAGER_CERT_HASH" <<'PY'
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
target = int(sys.argv[2])
cert_size = sys.argv[3]
cert_hash = sys.argv[4].lower()
kbuild = root / "kernel/Kbuild"
text = kbuild.read_text(encoding="utf-8")

text, count = re.subn(
    r'^KSU_VERSION\s*:=\s*\$\(if \$\(LOCAL_COUNT\),\$\(shell expr \$\(VERSION_BASE\) \+ \$\(LOCAL_COUNT\) - \$\(VERSION_OFFSET\)\),13000\)$',
    f'KSU_VERSION     := {target}',
    text,
    count=1,
    flags=re.MULTILINE,
)
if count == 0 and f"KSU_VERSION     := {target}" not in text:
    raise SystemExit("Cannot freeze SukiSU Ultra KSU_VERSION in kernel/Kbuild")

if cert_size or cert_hash:
    if not (re.fullmatch(r"0x[0-9a-fA-F]+", cert_size) and re.fullmatch(r"[0-9a-fA-F]{64}", cert_hash)):
        raise SystemExit("Custom manager certificate requires valid size and SHA-256 hash")
    text = re.sub(r'^KSU_EXPECTED_SIZE\s*:=\s*0x[0-9a-fA-F]+$', f'KSU_EXPECTED_SIZE := {cert_size}', text, count=1, flags=re.MULTILINE)
    text = re.sub(r'^KSU_EXPECTED_HASH\s*:=\s*[0-9a-fA-F]{64}$', f'KSU_EXPECTED_HASH := {cert_hash}', text, count=1, flags=re.MULTILINE)

kbuild.write_text(text, encoding="utf-8")

check = kbuild.read_text(encoding="utf-8")
if f"KSU_VERSION     := {target}" not in check:
    raise SystemExit("Frozen SukiSU Ultra KSU_VERSION marker missing")
if cert_size and cert_hash:
    if f"KSU_EXPECTED_SIZE := {cert_size}" not in check or f"KSU_EXPECTED_HASH := {cert_hash}" not in check:
        raise SystemExit("Configured SukiSU Ultra manager certificate marker missing")
PY

TAG=$(git -C "$KSU_ROOT" describe --abbrev=0 --tags 2>/dev/null || true)
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$ ]] || {
  echo "::error::Unexpected SukiSU Ultra release tag at $EXPECTED_COMMIT: ${TAG:-none}"
  exit 1
}

# KPM remains present in upstream SukiSU Ultra but must be disabled by the
# caller when add_kpm=false. Do not delete the upstream implementation; the
# exact feature state is audited from the final kernel .config.

echo "SukiSU Ultra source branch: $EXPECTED_BRANCH"
echo "SukiSU Ultra source commit: $EXPECTED_COMMIT"
echo "SukiSU Ultra requested version code: $TARGET_VERSION_CODE"
echo "SukiSU Ultra release tag: $TAG"
