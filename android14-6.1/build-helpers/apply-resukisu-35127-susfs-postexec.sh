#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common kernel tree is required}"
KSU_TREE="${2:?ReSukiSU tree is required}"

EXPECTED_RESUKISU_COMMIT="23a40c0f1dc047ee73a1dfd70a3f14df70021cac"
EXPECTED_SUSFS_BASE="5727f79e3a7175cfb0e1a754fc2ed78eaf866237"
UPSTREAM_SUSFS_FIX="153f88df3be2501d2d33364f8fe05247aecb3cef"

[[ "${RESUKISU_VERSION_CODE:-}" == "35127" ]] || {
  echo "::error::ReSukiSU 35127 post-exec port invoked for version ${RESUKISU_VERSION_CODE:-<unset>}"
  exit 1
}
[[ "${SUSFS_PINNED_COMMIT:-}" == "$EXPECTED_SUSFS_BASE" ]] || {
  echo "::error::Unexpected SUSFS base: ${SUSFS_PINNED_COMMIT:-<unset>}; expected $EXPECTED_SUSFS_BASE"
  exit 1
}
[[ -d "$COMMON_TREE" && -d "$KSU_TREE" ]] || {
  echo "::error::Kernel source trees are missing"
  exit 1
}

ACTUAL_RESUKISU_COMMIT=$(git -C "$KSU_TREE" rev-parse HEAD)
[[ "$ACTUAL_RESUKISU_COMMIT" == "$EXPECTED_RESUKISU_COMMIT" ]] || {
  echo "::error::ReSukiSU pin mismatch: expected $EXPECTED_RESUKISU_COMMIT, got $ACTUAL_RESUKISU_COMMIT"
  exit 1
}

python3 - "$COMMON_TREE/fs/exec.c" "$KSU_TREE/kernel/feature/sucompat.c" "$UPSTREAM_SUSFS_FIX" <<'PY'
from pathlib import Path
import re
import sys

exec_path = Path(sys.argv[1])
sucompat_path = Path(sys.argv[2])
upstream_fix = sys.argv[3]

if not exec_path.is_file() or not sucompat_path.is_file():
    raise SystemExit("required fs/exec.c or ReSukiSU sucompat.c is missing")

source = exec_path.read_text(encoding="utf-8")
sucompat = sucompat_path.read_text(encoding="utf-8")

required_ksu_markers = (
    "int ksu_handle_post_execve(",
    "int ksu_handle_post_execveat_sucompat(",
    "return ksu_handle_post_execveat(fd, filename_ptr, argv, envp, flags, retval);",
    "#ifndef KSU_COMPAT_HAS_SUSFS_INSTALL_SU_FD_DIRECT_CALL",
    "ksu_install_su_fd();",
)
for marker in required_ksu_markers:
    if marker not in sucompat:
        raise SystemExit(f"ReSukiSU 35127 post-exec contract marker is missing: {marker}")

if "ksu_handle_execveat_sucompat" not in source:
    raise SystemExit("pinned SUSFS exec pre-hook is missing; refusing unknown source state")

# 35127 owns the scoped [ksu_driver_su] installation. A direct call from
# fs/exec.c would cause susfs_compat.mk to disable the native 35127 path.
if "ksu_install_su_fd" in source:
    raise SystemExit("unexpected direct ksu_install_su_fd() call in fs/exec.c")

post_decl_re = re.compile(
    r"extern\s+int\s+ksu_handle_post_execveat_sucompat\s*\([^;]+;",
    re.DOTALL,
)
post_call_re = re.compile(
    r"ksu_handle_post_execveat_sucompat\s*\(\s*&fd\s*,\s*&filename\s*,\s*&argv\s*,\s*&envp\s*,\s*&flags\s*,\s*&retval\s*\)"
)

if not post_decl_re.search(source):
    pre_decl = re.search(
        r"extern\s+int\s+ksu_handle_execveat_sucompat\s*\([^;]+;\s*\n",
        source,
        re.DOTALL,
    )
    if not pre_decl:
        raise SystemExit("cannot locate the pinned SUSFS exec pre-hook declaration")
    declaration = (
        "extern int ksu_handle_post_execveat_sucompat(int *fd, struct filename **filename_ptr,\n"
        "\t\t\t\tvoid *argv, void *envp, int *flags, int *retval);\n"
    )
    source = source[:pre_decl.end()] + declaration + source[pre_decl.end():]

calls = list(post_call_re.finditer(source))
if len(calls) > 1:
    raise SystemExit(f"multiple post-exec SUSFS calls detected: {len(calls)}")

exec_matches = list(
    re.finditer(
        r"^[ \t]*retval\s*=\s*bprm_execve\(bprm, fd, filename, flags\);\s*$",
        source,
        re.MULTILINE,
    )
)
if len(exec_matches) != 1:
    raise SystemExit(f"expected one bprm_execve result assignment, found {len(exec_matches)}")

if not calls:
    line_end = source.find("\n", exec_matches[0].end())
    insert_at = exec_matches[0].end() if line_end < 0 else line_end + 1
    post_block = (
        "#ifdef CONFIG_KSU_SUSFS\n"
        "\t/* Simonpunk 153f88df ordering: create the scoped driver FD only\n"
        "\t * after a successful su exec has completed its CLOEXEC transition. */\n"
        "\tif (likely(retval >= 0))\n"
        "\t\tksu_handle_post_execveat_sucompat(&fd, &filename, &argv, &envp, &flags, &retval);\n"
        "#endif\n"
    )
    source = source[:insert_at] + post_block + source[insert_at:]

# Fail closed on source state and ordering.
exec_match = re.search(r"retval\s*=\s*bprm_execve\(bprm, fd, filename, flags\);", source)
post_calls = list(post_call_re.finditer(source))
if exec_match is None or len(post_calls) != 1:
    raise SystemExit("post-exec source verification failed")
if post_calls[0].start() <= exec_match.end():
    raise SystemExit("post-exec hook is not after bprm_execve")

window_start = max(0, post_calls[0].start() - 160)
window = source[window_start:post_calls[0].end()]
if not re.search(r"if\s*\(\s*likely\s*\(\s*retval\s*>=\s*0\s*\)\s*\)", window):
    raise SystemExit("post-exec hook is not gated on successful exec")
if "ksu_install_su_fd" in source:
    raise SystemExit("direct su FD installation unexpectedly appeared in fs/exec.c")

exec_path.write_text(source, encoding="utf-8")
print(
    "ReSukiSU 35127 / SUSFS post-exec contract applied: "
    f"base={EXPECTED_SUSFS_BASE if False else '5727f79e'}, upstream-ordering={upstream_fix}"
)
PY

# ReSukiSU's compatibility Makefiles consume these exact source probes:
# 1. A post-exec symbol in fs/exec.c disables the bprm_committed_creds fallback.
# 2. No direct ksu_install_su_fd() keeps 35127's native scoped-FD path enabled.
grep -qF 'ksu_handle_post_execveat_sucompat(&fd, &filename, &argv, &envp, &flags, &retval);' "$COMMON_TREE/fs/exec.c"
grep -Eq 'if[[:space:]]*\([[:space:]]*likely[[:space:]]*\([[:space:]]*retval[[:space:]]*>=[[:space:]]*0' "$COMMON_TREE/fs/exec.c"
! grep -qF 'ksu_install_su_fd' "$COMMON_TREE/fs/exec.c"
grep -qF 'grep -q "ksu_handle_post_execve" $(srctree)/fs/exec.c' "$KSU_TREE/kernel/tools/kernel_compat.mk"
grep -qF 'grep -q "ksu_install_su_fd" $(srctree)/fs/exec.c' "$KSU_TREE/kernel/tools/susfs_compat.mk"

echo "Verified ReSukiSU 35127 native UAPI4 post-exec path against SUSFS $EXPECTED_SUSFS_BASE"
