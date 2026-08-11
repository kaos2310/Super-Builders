#!/bin/bash
set -euo pipefail

COMMON_TREE="$(cd "${1:?common tree}" && pwd)"
SOURCE="$COMMON_TREE/fs/namespace.c"
PYTHON_BIN="${PYTHON_BIN:-python3}"
[[ -f "$SOURCE" ]] || {
  echo "::error::Samsung namespace source is unavailable: $SOURCE"
  exit 1
}

"$PYTHON_BIN" - "$SOURCE" <<'PY'
from pathlib import Path
import re
import sys

source = Path(sys.argv[1])
text = source.read_text(encoding="utf-8")

marker_re = re.compile(
    r"^#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    r"^[ \t]*copy_flags \|= CL_COPY_MNT_NS;\n"
    r"^#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n?",
    re.MULTILINE,
)
matches = list(marker_re.finditer(text))
if len(matches) != 1:
    raise SystemExit(
        f"Expected exactly one SUSFS copy_mnt_ns marker block, found {len(matches)}"
    )

# GNU patch with fuzz 3 can match this small hunk against copy_mount_options()
# in Samsung's tree. Remove the uniquely identified block first, then anchor it
# inside copy_mnt_ns() using the surrounding copy_flags statements.
text = marker_re.sub("", text, count=1)
signature = "struct mnt_namespace *copy_mnt_ns(unsigned long flags, struct mnt_namespace *ns,"
function_start = text.find(signature)
if function_start < 0:
    raise SystemExit("Samsung copy_mnt_ns() signature was not found")

next_signature = "\nstruct dentry *mount_subtree(struct vfsmount *m, const char *name)"
function_end = text.find(next_signature, function_start)
if function_end < 0:
    raise SystemExit("Samsung mount_subtree() boundary after copy_mnt_ns() was not found")

function = text[function_start:function_end]
anchor_re = re.compile(
    r"(^[ \t]*copy_flags = CL_COPY_UNBINDABLE \| CL_EXPIRE;\n"
    r"^[ \t]*if \(user_ns != ns->user_ns\)\n"
    r"^[ \t]*copy_flags \|= CL_SHARED_TO_SLAVE;\n)",
    re.MULTILINE,
)
anchors = list(anchor_re.finditer(function))
if len(anchors) != 1:
    raise SystemExit(
        f"Expected one Samsung copy_mnt_ns() copy_flags anchor, found {len(anchors)}"
    )

marker = (
    "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
    "\tcopy_flags |= CL_COPY_MNT_NS;\n"
    "#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
)
insert_at = function_start + anchors[0].end()
text = text[:insert_at] + marker + text[insert_at:]

if len(list(marker_re.finditer(text))) != 1:
    raise SystemExit("Relocated SUSFS copy_mnt_ns marker is not unique")
function_end += len(marker)
function = text[function_start:function_end]
marker_offset = function.find("copy_flags |= CL_COPY_MNT_NS;")
copy_tree_offset = function.find("new = copy_tree(")
if marker_offset < 0 or copy_tree_offset < 0 or marker_offset > copy_tree_offset:
    raise SystemExit("Relocated SUSFS marker is outside the copy_mnt_ns copy-tree path")
if "int copy_flags;" not in function[:marker_offset]:
    raise SystemExit("copy_flags is not declared before the relocated SUSFS marker")

with source.open("w", encoding="utf-8", newline="") as output:
    output.write(text)
PY

grep -q '^struct mnt_namespace \*copy_mnt_ns' "$SOURCE"
test "$(grep -cF 'copy_flags |= CL_COPY_MNT_NS;' "$SOURCE")" = 1
echo "Relocated Samsung DZG1 SUSFS copy_mnt_ns flag into its declared scope"
