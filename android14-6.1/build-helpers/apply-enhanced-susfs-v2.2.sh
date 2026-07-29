#!/bin/bash
set -euo pipefail

COMMON="${1:?kernel common tree is required}"
KSU_ROOT="${2:?KernelSU root is required}"
SOURCE_PATCH="${3:?enhanced SUSFS patch is required}"
WORK_DIR="${RUNNER_TEMP:-/tmp}/susfs-enhanced-v2.2"

[[ -d "$COMMON" ]] || { echo "::error::Kernel common tree is missing: $COMMON"; exit 1; }
[[ -d "$KSU_ROOT" ]] || { echo "::error::KernelSU tree is missing: $KSU_ROOT"; exit 1; }
[[ -s "$SOURCE_PATCH" ]] || { echo "::error::Enhanced SUSFS patch is missing: $SOURCE_PATCH"; exit 1; }
mkdir -p "$WORK_DIR"

extract_matching_hunks() {
  local source_patch="$1"
  local target_path="$2"
  local hunk_pattern="$3"
  local output_patch="$4"

  python3 - "$source_patch" "$target_path" "$hunk_pattern" "$output_patch" <<'PY'
import pathlib
import re
import sys

source, target, expression, output = sys.argv[1:]
lines = pathlib.Path(source).read_text(encoding="utf-8").splitlines(keepends=True)

start = None
for index, line in enumerate(lines):
    if line.startswith("--- ") and re.search(rf"/{re.escape(target)}(?:\t|\r?\n$)", line):
        start = index
        break
if start is None:
    raise SystemExit(f"No patch section found for {target}")

end = len(lines)
for index in range(start + 1, len(lines)):
    if lines[index].startswith("diff "):
        end = index
        break

section = lines[start:end]
first_hunk = next((index for index, line in enumerate(section) if line.startswith("@@")), None)
if first_hunk is None:
    raise SystemExit(f"No hunks found for {target}")

header = section[:first_hunk]
hunks = []
current = []
for line in section[first_hunk:]:
    if line.startswith("@@"):
        if current:
            hunks.append(current)
        current = [line]
    else:
        current.append(line)
if current:
    hunks.append(current)

pattern = re.compile(expression)
selected = [hunk for hunk in hunks if pattern.search("".join(hunk))]
if not selected:
    raise SystemExit(f"No matching hunks for {target}: {expression}")

pathlib.Path(output).write_text(
    "".join(header + [line for hunk in selected for line in hunk]),
    encoding="utf-8",
)
PY
}

apply_required_hunks() {
  local target_path="$1"
  local hunk_pattern="$2"
  local output_patch="$WORK_DIR/$(echo "$target_path" | tr '/' '_').patch"

  extract_matching_hunks "$SOURCE_PATCH" "$target_path" "$hunk_pattern" "$output_patch"

  if patch -d "$COMMON" -p1 -F3 --forward --batch --dry-run < "$output_patch" >/dev/null 2>&1; then
    echo "Applying enhanced SUSFS v2.2 hooks: $target_path"
    patch -d "$COMMON" -p1 -F3 --forward --batch --no-backup-if-mismatch < "$output_patch"
    return 0
  fi

  if patch -d "$COMMON" -R -p1 -F3 --forward --batch --dry-run < "$output_patch" >/dev/null 2>&1; then
    echo "Enhanced SUSFS v2.2 hooks already present: $target_path"
    return 0
  fi

  echo "::error::Required enhanced SUSFS v2.2 hunks do not apply cleanly: $target_path"
  patch -d "$COMMON" -p1 -F3 --forward --batch --dry-run < "$output_patch" || true
  return 1
}

apply_required_hunks 'fs/Kconfig' \
  'KSU_SUSFS_SUS_KSTAT_REDIRECT|KSU_SUSFS_UNICODE_FILTER|KSU_SUSFS_HIDDEN_NAME'
apply_required_hunks 'include/linux/susfs_def.h' \
  'CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT'
apply_required_hunks 'include/linux/susfs.h' \
  'struct super_block|st_susfs_sus_kstat_redirect|susfs_add_sus_kstat_redirect|KSU_SUSFS_UNICODE_FILTER|susfs_check_unicode_bypass|susfs_is_hidden_name|susfs_is_hidden_ino'
apply_required_hunks 'fs/namei.c' \
  'KSU_SUSFS_UNICODE_FILTER|susfs_check_unicode_bypass'
apply_required_hunks 'fs/open.c' \
  'KSU_SUSFS_HIDDEN_NAME|KSU_SUSFS_UNICODE_FILTER|susfs_is_hidden_name|susfs_check_unicode_bypass'
apply_required_hunks 'fs/stat.c' \
  'KSU_SUSFS_HIDDEN_NAME|KSU_SUSFS_UNICODE_FILTER|susfs_is_hidden_name|susfs_check_unicode_bypass'
apply_required_hunks 'fs/susfs.c' \
  'KSU_SUSFS_UNICODE_FILTER|susfs_check_unicode_bypass|struct susfs_hidden_name_entry|susfs_try_register_hidden_name|KSU_SUSFS_SUS_KSTAT_REDIRECT|susfs_add_sus_kstat_redirect'

python3 - "$KSU_ROOT" "$COMMON" <<'PY'
import pathlib
import re
import sys

ksu_root = pathlib.Path(sys.argv[1])
common = pathlib.Path(sys.argv[2])
candidates = [
    ksu_root / "kernel/supercall/dispatch.c",
    common / "drivers/kernelsu/supercall/dispatch.c",
]
seen = set()
handled = 0

for candidate in candidates:
    if not candidate.exists():
        continue
    resolved = candidate.resolve()
    if resolved in seen:
        continue
    seen.add(resolved)

    text = candidate.read_text(encoding="utf-8")
    if "CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT" in text:
        handled += 1
        continue

    pattern = re.compile(
        r"(?P<indent>^[ \t]*)case CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY:\n"
        r"(?P=indent)[ \t]+susfs_add_sus_kstat\(arg\);\n"
        r"(?P=indent)[ \t]+return 0;\n",
        re.MULTILINE,
    )
    match = pattern.search(text)
    if not match:
        raise SystemExit(f"Cannot locate SUSFS kstat dispatch block in {candidate}")

    indent = match.group("indent")
    block = (
        match.group(0)
        + "#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT_REDIRECT\n"
        + f"{indent}case CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT:\n"
        + f"{indent}    susfs_add_sus_kstat_redirect(arg);\n"
        + f"{indent}    return 0;\n"
        + "#endif // CONFIG_KSU_SUSFS_SUS_KSTAT_REDIRECT\n"
    )
    candidate.write_text(text[:match.start()] + block + text[match.end():], encoding="utf-8")
    handled += 1
    print(f"Added kstat redirect dispatch: {candidate}")

if handled == 0:
    raise SystemExit("No SukiSU SUSFS dispatch source was found")
PY

for symbol in \
  KSU_SUSFS_SUS_KSTAT_REDIRECT \
  KSU_SUSFS_UNICODE_FILTER \
  KSU_SUSFS_HIDDEN_NAME; do
  grep -Rqx "config ${symbol}" "$COMMON" --include='Kconfig*' || {
    echo "::error::Enhanced SUSFS symbol is missing after targeted apply: ${symbol}"
    exit 1
  }
done

grep -q 'CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT' "$COMMON/include/linux/susfs_def.h"
grep -q 'struct st_susfs_sus_kstat_redirect' "$COMMON/include/linux/susfs.h"
grep -q 'void susfs_add_sus_kstat_redirect' "$COMMON/fs/susfs.c"
grep -q 'susfs_check_unicode_bypass' "$COMMON/fs/namei.c"
grep -q 'susfs_is_hidden_name' "$COMMON/fs/open.c"
grep -q 'susfs_is_hidden_name' "$COMMON/fs/stat.c"
grep -Rq 'case CMD_SUSFS_ADD_SUS_KSTAT_REDIRECT:' \
  "$KSU_ROOT/kernel" "$COMMON/drivers/kernelsu" 2>/dev/null

echo "Enhanced SUSFS v2.2 features applied and audited."
