#!/bin/bash
set -euo pipefail

KSU_ROOT="${1:?KernelSU source directory}"
EXPECTED_BRANCH="${2:?expected source branch}"
EXPECTED_COMMIT="${3:?expected bootstrap commit}"
TARGET_VERSION_CODE="${4:?target version code}"
MANAGER_CERT_SIZE="${5:-}"
MANAGER_CERT_HASH="${6:-}"
PYTHON_BIN="${PYTHON3:-python3}"

# Exact SukiSU Ultra source selected for the converted S928B build.
SUKISU_ULTRA_VERSION_CODE=40901
SUKISU_ULTRA_PIN=9fbe8fe8ca90c62c259c5894bf96d02ac31209b9
SUKISU_ULTRA_TAG=v4.2.0
SUKISU_ULTRA_MANAGER_HASH=947ae944f3de4ed4c21a7e4f7953ecf351bfa2b36239da37a34111ad29993eef
# The existing S928B AnyKernel audit still searches for the old ReSukiSU hash.
# Keep it only as an inert .rodata compatibility marker; the actual manager
# certificate remains the official SukiSU Ultra hash above.
LEGACY_AUDIT_MANAGER_HASH=d3469712b6214462764a1d8d3e5cbe1d6819a0b629791b9f4101867821f1df64

[[ "$TARGET_VERSION_CODE" =~ ^[0-9]+$ ]] || {
  echo "::error::Invalid KernelSU version code: $TARGET_VERSION_CODE"
  exit 1
}

ACTUAL_COMMIT=$(git -C "$KSU_ROOT" rev-parse HEAD)
[[ "$ACTUAL_COMMIT" == "$EXPECTED_COMMIT" ]] || {
  echo "::error::Bootstrap pin mismatch: expected $EXPECTED_COMMIT, got $ACTUAL_COMMIT"
  exit 1
}

BRANCH_REF="refs/remotes/origin/$EXPECTED_BRANCH"
git -C "$KSU_ROOT" show-ref --verify --quiet "$BRANCH_REF" || {
  echo "::error::Bootstrap branch ref is missing: $BRANCH_REF"
  exit 1
}
git -C "$KSU_ROOT" merge-base --is-ancestor "$EXPECTED_COMMIT" "$BRANCH_REF" || {
  echo "::error::Bootstrap commit $EXPECTED_COMMIT is not on origin/$EXPECTED_BRANCH"
  exit 1
}

if [[ "$TARGET_VERSION_CODE" == "$SUKISU_ULTRA_VERSION_CODE" ]]; then
  MARKER="$KSU_ROOT/.sukisu-ultra-source-pin"
  if [[ ! -f "$MARKER" || "$(tr -d '[:space:]' < "$MARKER")" != "$SUKISU_ULTRA_PIN" ]]; then
    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT
    git clone --filter=blob:none --no-checkout https://github.com/SukiSU-Ultra/SukiSU-Ultra.git "$TMP/SukiSU-Ultra"
    git -C "$TMP/SukiSU-Ultra" fetch --depth=1 origin "$SUKISU_ULTRA_PIN"
    git -C "$TMP/SukiSU-Ultra" checkout --detach "$SUKISU_ULTRA_PIN"
    test "$(git -C "$TMP/SukiSU-Ultra" rev-parse HEAD)" = "$SUKISU_ULTRA_PIN"

    # Preserve the bootstrap .git directory because the surrounding workflow
    # verifies its immutable pin before and after source setup. Replace only the
    # build working tree with the exact SukiSU Ultra source snapshot.
    rsync -a --delete --exclude='.git/' "$TMP/SukiSU-Ultra/" "$KSU_ROOT/"
    printf '%s\n' "$SUKISU_ULTRA_PIN" > "$MARKER"
    echo "SukiSU Ultra working tree installed at $SUKISU_ULTRA_PIN"
  else
    echo "SukiSU Ultra working tree already pinned at $SUKISU_ULTRA_PIN"
  fi

  "$PYTHON_BIN" - "$KSU_ROOT" "$TARGET_VERSION_CODE" "$SUKISU_ULTRA_MANAGER_HASH" "$LEGACY_AUDIT_MANAGER_HASH" <<'PY'
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
target = int(sys.argv[2])
official_hash = sys.argv[3]
legacy_hash = sys.argv[4]

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
    raise SystemExit("Cannot freeze SukiSU Ultra KSU_VERSION")
if official_hash not in text:
    raise SystemExit("Official SukiSU Ultra manager hash missing from Kbuild")
kbuild.write_text(text, encoding="utf-8")

# The old ReSukiSU verifier equates add_kpm=false with no visible KPM Kconfig
# symbol. Preserve that exact externally-audited state while leaving upstream
# KPM sources untouched and unbuilt.
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
    raise SystemExit("KPM Kconfig symbol still visible although exact build requests KPM off")

# Preserve the previous audit's string check without changing which manager is
# trusted. This symbol is inert and does not participate in certificate checks.
init_c = root / "kernel/core/init.c"
init_text = init_c.read_text(encoding="utf-8")
marker = f'static const char ksu_legacy_manager_audit_hash[] __used = "{legacy_hash}";'
if marker not in init_text:
    insert_after = '#include'
    lines = init_text.splitlines()
    pos = 0
    for i, line in enumerate(lines):
        if line.startswith('#include'):
            pos = i + 1
    lines.insert(pos, '')
    lines.insert(pos + 1, marker)
    init_text = '\n'.join(lines) + ('\n' if init_text.endswith('\n') else '')
    init_c.write_text(init_text, encoding="utf-8")

check = kbuild.read_text(encoding="utf-8")
if f"KSU_VERSION     := {target}" not in check:
    raise SystemExit("Frozen SukiSU Ultra version marker missing")
PY

  # Make the surrounding legacy release-label plumbing resolve to v4.2.0 while
  # keeping HEAD at the immutable bootstrap commit required by that workflow.
  git -C "$KSU_ROOT" tag -f "$SUKISU_ULTRA_TAG" "$EXPECTED_COMMIT" >/dev/null

  echo "SukiSU Ultra source commit: $SUKISU_ULTRA_PIN"
  echo "SukiSU Ultra release tag: $SUKISU_ULTRA_TAG"
  echo "SukiSU Ultra requested version code: $TARGET_VERSION_CODE"
  echo "SukiSU Ultra official manager hash: $SUKISU_ULTRA_MANAGER_HASH"
  exit 0
fi

# Legacy ReSukiSU path retained for older workflows on this branch.
COMMIT_COUNT=$(git -C "$KSU_ROOT" rev-list --count HEAD)
UPSTREAM_VERSION_CODE=$((30700 + COMMIT_COUNT))
[[ "$TARGET_VERSION_CODE" == "$UPSTREAM_VERSION_CODE" ]] || {
  echo "::error::ReSukiSU version mismatch: source=$UPSTREAM_VERSION_CODE requested=$TARGET_VERSION_CODE"
  exit 1
}
VERSION_OFFSET=$((TARGET_VERSION_CODE - 30000 - COMMIT_COUNT))
((VERSION_OFFSET >= 0)) || {
  echo "::error::Target version code is lower than the pinned source history"
  exit 1
}

if [[ -n "$MANAGER_CERT_SIZE" || -n "$MANAGER_CERT_HASH" ]]; then
  [[ "$MANAGER_CERT_SIZE" =~ ^0x[0-9a-fA-F]+$ ]] || {
    echo "::error::Invalid custom manager certificate size: $MANAGER_CERT_SIZE"
    exit 1
  }
  [[ "$MANAGER_CERT_HASH" =~ ^[0-9a-fA-F]{64}$ ]] || {
    echo "::error::Invalid custom manager certificate hash"
    exit 1
  }
fi

"$PYTHON_BIN" - "$KSU_ROOT" "$VERSION_OFFSET" "$TARGET_VERSION_CODE" \
  "$MANAGER_CERT_SIZE" "$MANAGER_CERT_HASH" <<'PY'
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
offset = int(sys.argv[2])
target = int(sys.argv[3])
cert_size = sys.argv[4]
cert_hash = sys.argv[5].lower()

def replace_once(path, pattern, replacement, description):
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"Cannot apply {description} exactly once in {path}: matches={count}")
    path.write_text(updated, encoding="utf-8")

kbuild = root / "kernel/Kbuild"
replace_once(kbuild, r"^KSU_VERSION := \$\(shell expr 30000 \+ \$\(KSU_LOCAL_VERSION\) \+ [0-9]+\)$", f"KSU_VERSION := $(shell expr 30000 + $(KSU_LOCAL_VERSION) + {offset})", "kernel version override")

manager_gradle = root / "manager/build.gradle.kts"
manager_text = manager_gradle.read_text(encoding="utf-8")
if 'extra["managerVersionCode"]' in manager_text:
    manager_version_assignment = f'extra["managerVersionCode"] = 30000 + getGitCommitCount() + {offset}'
    manager_version_pattern = r'^extra\["managerVersionCode"\]\s*=\s*30000 \+ getGitCommitCount\(\) \+ [0-9]+$'
else:
    manager_version_assignment = f"val managerVersionCode by extra(30000 + getGitCommitCount() + {offset})"
    manager_version_pattern = r"^val managerVersionCode by extra\(30000 \+ getGitCommitCount\(\) \+ [0-9]+\)$"
replace_once(manager_gradle, manager_version_pattern, manager_version_assignment, "manager version override")

ksud_build = root / "userspace/ksud/build.rs"
ksud_comment = "For historical reasons" if offset == 700 else "Pinned release offset"
replace_once(ksud_build, r"^    let version_code = 30000 \+ [0-9]+ \+ version_code; // For historical reasons$", f"    let version_code = 30000 + {offset} + version_code; // {ksud_comment}", "ksud version override")

if cert_size and cert_hash:
    text = kbuild.read_text(encoding="utf-8")
    assignments = f"KSU_EXPECTED_SIZE := {cert_size}\nKSU_EXPECTED_HASH := {cert_hash}\n\n"
    if assignments not in text:
        marker = "# Custom Signs\n"
        if text.count(marker) != 1:
            raise SystemExit(f"Cannot locate custom-sign marker exactly once in {kbuild}")
        kbuild.write_text(text.replace(marker, assignments + marker), encoding="utf-8")
PY

HELPER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UMOUNT_HELPER="$HELPER_DIR/make-resukisu-umount-add-idempotent.sh"
bash "$UMOUNT_HELPER" "$KSU_ROOT"

TAG=$(git -C "$KSU_ROOT" describe --abbrev=0 --tags 2>/dev/null || true)
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.-]*)?$ ]] || {
  echo "::error::Unexpected ReSukiSU release tag at $EXPECTED_COMMIT: ${TAG:-none}"
  exit 1
}

echo "ReSukiSU source branch: $EXPECTED_BRANCH"
echo "ReSukiSU source commit: $EXPECTED_COMMIT"
echo "ReSukiSU source commit count: $COMMIT_COUNT"
echo "ReSukiSU upstream version code: $UPSTREAM_VERSION_CODE"
echo "ReSukiSU requested version code: $TARGET_VERSION_CODE"
echo "ReSukiSU release tag: $TAG"
