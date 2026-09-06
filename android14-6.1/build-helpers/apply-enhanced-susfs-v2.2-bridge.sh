#!/bin/bash
set -euo pipefail

COMMON="${1:?kernel common tree is required}"
KSU_ROOT="${2:?KernelSU root is required}"
SOURCE_PATCH="${3:?enhanced SUSFS patch is required}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CORE_HELPER="$SCRIPT_DIR/apply-enhanced-susfs-v2.2-core.sh"
SUSFS_TREE="${SUSFS_FOLDER:-}"
WORK_DIR="${RUNNER_TEMP:-/tmp}/sukisu-susfs-kernel-bridge"

[[ -d "$COMMON" ]] || { echo "::error::Kernel common tree is missing: $COMMON"; exit 1; }
[[ -d "$KSU_ROOT" ]] || { echo "::error::SukiSU tree is missing: $KSU_ROOT"; exit 1; }
[[ -x "$CORE_HELPER" || -f "$CORE_HELPER" ]] || { echo "::error::Enhanced SUSFS core helper is missing: $CORE_HELPER"; exit 1; }
[[ -n "$SUSFS_TREE" && -d "$SUSFS_TREE" ]] || { echo "::error::Pinned SUSFS tree is unavailable (SUSFS_FOLDER=${SUSFS_TREE:-<unset>})"; exit 1; }

KSU_SUSFS_PATCH="$SUSFS_TREE/kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch"
[[ -s "$KSU_SUSFS_PATCH" ]] || { echo "::error::Pinned SUSFS KernelSU integration patch is missing: $KSU_SUSFS_PATCH"; exit 1; }

DISPATCH="$KSU_ROOT/kernel/supercall/dispatch.c"
INIT_C="$KSU_ROOT/kernel/core/init.c"
rm -rf "$WORK_DIR"
mkdir -p "$WORK_DIR/hunks"

# The pinned SUSFS v2.3.0 KernelSU patch is based on a nearby SukiSU/KernelSU
# layout, but SukiSU Ultra v4.2.0 has newer lifecycle and hook-manager code.
# Applying the complete patch as one unit therefore fails on two core/init.c
# contexts even though the SUSFS dispatcher and the other integration hunks
# are compatible. Split the patch into single hunks and apply each one
# fail-closed. Only incompatible core/init.c hunks are allowed to be skipped;
# SUSFS initialization is then ported structurally without replacing SukiSU's
# v4.2.0 hook architecture.
python3 - "$KSU_SUSFS_PATCH" "$WORK_DIR/hunks" "$WORK_DIR/manifest.tsv" <<'PY'
from pathlib import Path
import re
import sys

patch_path = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
manifest = Path(sys.argv[3])
lines = patch_path.read_text(encoding="utf-8").splitlines(keepends=True)
out_dir.mkdir(parents=True, exist_ok=True)

sections = []
start = None
for i, line in enumerate(lines):
    if line.startswith("diff --git "):
        if start is not None:
            sections.append(lines[start:i])
        start = i
if start is not None:
    sections.append(lines[start:])
if not sections:
    raise SystemExit("Pinned SUSFS KernelSU patch has no diff sections")

records = []
index = 0
for section in sections:
    first_hunk = next((i for i, line in enumerate(section) if line.startswith("@@ ")), None)
    if first_hunk is None:
        continue
    header = section[:first_hunk]
    plus = next((line for line in header if line.startswith("+++ ")), None)
    if not plus:
        raise SystemExit("SUSFS patch section has no +++ target")
    target = plus[4:].split("\t", 1)[0].strip()
    target = re.sub(r"^[ab]/", "", target)

    hunks = []
    current = []
    for line in section[first_hunk:]:
        if line.startswith("@@ "):
            if current:
                hunks.append(current)
            current = [line]
        else:
            current.append(line)
    if current:
        hunks.append(current)

    for hunk in hunks:
        index += 1
        path = out_dir / f"{index:03d}.patch"
        path.write_text("".join(header + hunk), encoding="utf-8")
        records.append((target, str(path)))

manifest.write_text("".join(f"{target}\t{path}\n" for target, path in records), encoding="utf-8")
print(f"Prepared {len(records)} pinned SUSFS KernelSU hunks")
PY

applied=0
already=0
skipped_init=0
while IFS=$'\t' read -r target hunk_patch; do
  [[ -n "$target" && -s "$hunk_patch" ]] || continue

  if patch -d "$KSU_ROOT" -p1 -F3 --forward --batch --dry-run < "$hunk_patch" >/dev/null 2>&1; then
    patch -d "$KSU_ROOT" -p1 -F3 --forward --batch --no-backup-if-mismatch < "$hunk_patch" >/dev/null
    applied=$((applied + 1))
    continue
  fi

  if patch -d "$KSU_ROOT" -R -p1 -F3 --batch --dry-run < "$hunk_patch" >/dev/null 2>&1; then
    already=$((already + 1))
    continue
  fi

  if [[ "$target" == "kernel/core/init.c" ]]; then
    skipped_init=$((skipped_init + 1))
    echo "::notice::Structurally porting incompatible SUSFS core/init.c hunk: $(basename "$hunk_patch")"
    continue
  fi

  echo "::error::Pinned SUSFS KernelSU hunk does not apply cleanly to SukiSU v4.2.0: $target ($(basename "$hunk_patch"))"
  echo "::group::Failed SUSFS hunk"
  cat "$hunk_patch"
  echo "::endgroup::"
  patch -d "$KSU_ROOT" -p1 -F3 --forward --batch --dry-run < "$hunk_patch" || true
  exit 1
done < "$WORK_DIR/manifest.tsv"

echo "Pinned SUSFS KernelSU hunk port: applied=$applied already=$already core_init_structural=$skipped_init"

# Preserve SukiSU v4.2.0's syscall-hook manager/lifecycle. The SUSFS-specific
# core requirement is the header plus susfs_init() before feature consumers.
# This is idempotent and exact-anchor checked.
python3 - "$INIT_C" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

include_block = "#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs.h>\n#endif\n"
if "#include <linux/susfs.h>" not in text:
    anchors = [
        "#include <linux/moduleparam.h>\n",
        "#include <linux/workqueue.h>\n",
    ]
    anchor = next((a for a in anchors if text.count(a) == 1), None)
    if anchor is None:
        raise SystemExit("Cannot locate a unique include anchor in SukiSU core/init.c")
    text = text.replace(anchor, anchor + "\n" + include_block, 1)

if "susfs_init();" not in text:
    anchor = "    ksu_feature_init();\n"
    if text.count(anchor) != 1:
        raise SystemExit(f"Expected one ksu_feature_init() anchor, found {text.count(anchor)}")
    init_block = (
        "#ifdef CONFIG_KSU_SUSFS\n"
        "    susfs_init();\n"
        "#endif // CONFIG_KSU_SUSFS\n\n"
    )
    text = text.replace(anchor, init_block + anchor, 1)

if text.count("#include <linux/susfs.h>") != 1:
    raise SystemExit("SUSFS include is missing or duplicated in SukiSU core/init.c")
if text.count("susfs_init();") != 1:
    raise SystemExit("susfs_init() is missing or duplicated in SukiSU core/init.c")

path.write_text(text, encoding="utf-8")
print("Verified structural SukiSU v4.2.0 SUSFS initialization port")
PY

# SukiSU 4.2 modern SUSFS reboot bridge normalization
# Simonpunk v2.3.0 installs ksu_handle_sys_reboot(); extract its exact
# SUSFS switch into the narrow dispatcher expected by the enhanced
# SUSFS/ZeroMount adapters rather than maintaining a second command list.
[[ -f "$DISPATCH" ]] || { echo "::error::SukiSU SUSFS dispatcher source is missing after integration: $DISPATCH"; exit 1; }
NORMALIZER="$SCRIPT_DIR/normalize-sukisu-susfs-dispatch.py"
[[ -s "$NORMALIZER" ]] || { echo "::error::SukiSU SUSFS dispatcher normalizer is missing: $NORMALIZER"; exit 1; }
python3 "$NORMALIZER" "$DISPATCH"

SUPERCALL_C="$KSU_ROOT/kernel/supercall/supercall.c"
SUPERCALL_H="$KSU_ROOT/kernel/supercall/supercall.h"
REBOOT_C="$COMMON/kernel/reboot.c"
[[ -f "$SUPERCALL_C" && -f "$SUPERCALL_H" && -f "$REBOOT_C" ]] || {
  echo "::error::SukiSU/SUSFS reboot bridge source set is incomplete"
  exit 1
}
grep -qF 'int ksu_handle_susfs_cmd(' "$DISPATCH" || { echo "::error::SUSFS split dispatcher normalization failed"; exit 1; }
grep -qF 'int ksu_handle_sys_reboot(' "$DISPATCH" || { echo "::error::Modern SukiSU reboot dispatcher is missing"; exit 1; }
grep -qF 'return ksu_handle_susfs_cmd(cmd, arg);' "$DISPATCH" || { echo "::error::Modern reboot dispatcher does not delegate SUSFS commands"; exit 1; }
grep -qF '#include <linux/susfs.h>' "$DISPATCH" || { echo "::error::SUSFS dispatch include is missing"; exit 1; }
grep -qF 'CMD_SUSFS_ADD_SUS_KSTAT_STATICALLY' "$DISPATCH" || { echo "::error::SUS_KSTAT dispatch is missing"; exit 1; }
grep -qF 'int ksu_supercall_reboot_handler(void __user **arg)' "$SUPERCALL_C" || { echo "::error::ksu_supercall_reboot_handler() implementation is missing"; exit 1; }
grep -qF 'int ksu_supercall_reboot_handler(void __user **arg);' "$SUPERCALL_H" || { echo "::error::ksu_supercall_reboot_handler() declaration is missing"; exit 1; }
if grep -qF 'reboot_handler_pre' "$SUPERCALL_C"; then
  echo "::error::Legacy reboot kprobe survived the direct SUSFS reboot integration"
  exit 1
fi
grep -qF 'ksu_handle_sys_reboot' "$REBOOT_C" || { echo "::error::kernel/reboot.c is not wired to the SukiSU/SUSFS dispatcher"; exit 1; }
grep -qF 'config KSU_SUSFS' "$KSU_ROOT/kernel/Kconfig" || { echo "::error::CONFIG_KSU_SUSFS integration is missing"; exit 1; }
grep -qF 'susfs_init();' "$INIT_C"

# Reject accidental patch leftovers before the enhanced/ZeroMount adapters run.
if find "$KSU_ROOT/kernel" -type f \( -name '*.rej' -o -name '*.orig' \) -print -quit | grep -q .; then
  echo "::error::SUSFS SukiSU bridge left patch rejects/backups"
  find "$KSU_ROOT/kernel" -type f \( -name '*.rej' -o -name '*.orig' \) -print
  exit 1
fi

echo "Pinned SUSFS 2.3.0 KernelSU bridge ported to SukiSU Ultra v4.2.0."
chmod +x "$CORE_HELPER"
exec "$CORE_HELPER" "$COMMON" "$KSU_ROOT" "$SOURCE_PATCH"
