#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common kernel tree}"
KSU_TREE="${2:?KernelSU tree}"

# ReSukiSU 35127/UAPI4 already contains the native scoped su-session FD code.
# Keep the proven SUSFS v2.3.0 base used by the successful 35119 build, and
# backport only Simonpunk's 153f88df post-exec ordering to the 6.1.162 exec
# hook. Do not re-apply the obsolete 35119/UAPI2 cross-tree port.
if [[ "${RESUKISU_VERSION_CODE:-}" == "35127" ]]; then
  POSTEXEC_HELPER="$(dirname "$0")/apply-resukisu-35127-susfs-postexec.sh"
  [[ -s "$POSTEXEC_HELPER" ]] || {
    echo "::error::ReSukiSU 35127 post-exec helper is missing: $POSTEXEC_HELPER"
    exit 1
  }
  chmod +x "$POSTEXEC_HELPER"
  "$POSTEXEC_HELPER" "$COMMON_TREE" "$KSU_TREE"

  # Independent CI gate: do not trust only the helper's own verification.
  # The scoped [ksu_driver_su] hand-off must remain after bprm_execve(), must
  # be guarded by retval >= 0, and fs/exec.c must never install the FD directly.
  python3 - "$COMMON_TREE/fs/exec.c" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
source = path.read_text(encoding="utf-8")

exec_matches = list(re.finditer(
    r"retval\s*=\s*bprm_execve\(bprm, fd, filename, flags\);",
    source,
))
post_matches = list(re.finditer(
    r"ksu_handle_post_execveat_sucompat\s*\(\s*&fd\s*,\s*&filename\s*,\s*&argv\s*,\s*&envp\s*,\s*&flags\s*,\s*&retval\s*\)",
    source,
))

if len(exec_matches) != 1:
    raise SystemExit(f"expected exactly one bprm_execve assignment, found {len(exec_matches)}")
if len(post_matches) != 1:
    raise SystemExit(f"expected exactly one 35127 post-exec call, found {len(post_matches)}")
if post_matches[0].start() <= exec_matches[0].end():
    raise SystemExit("35127 post-exec hook is not after bprm_execve")

window = source[max(0, post_matches[0].start() - 192):post_matches[0].end()]
if not re.search(r"if\s*\(\s*likely\s*\(\s*retval\s*>=\s*0\s*\)\s*\)", window):
    raise SystemExit("35127 post-exec hook is not guarded by likely(retval >= 0)")
if "ksu_install_su_fd" in source:
    raise SystemExit("direct ksu_install_su_fd() call reappeared in fs/exec.c")

print("Verified independent 35127 success-only post-exec gate: bprm_execve -> retval >= 0 -> scoped su FD")
PY
fi

require_source() {
  local relative="$1"
  local needle="$2"
  local path="$COMMON_TREE/$relative"
  [[ -f "$path" ]] || {
    echo "::error::ZeroMount/SUSFS source is missing: $relative"
    exit 1
  }
  grep -qF "$needle" "$path" || {
    echo "::error::ZeroMount/SUSFS hook is missing from $relative: $needle"
    exit 1
  }
}

require_source fs/Kconfig 'config ZEROMOUNT'
require_source fs/Makefile 'obj-$(CONFIG_ZEROMOUNT)'
require_source fs/zeromount.c 'zeromount_ioctl_add_rule'
require_source fs/zeromount.c 'zeromount_inject_dents64'
require_source fs/zeromount.c 'zeromount_is_uid_blocked'
require_source fs/zeromount.c 'zeromount_spoof_statfs'
require_source fs/zeromount.c 'kern_path(statfs_root, LOOKUP_FOLLOW, &root_path)'
require_source fs/zeromount.c '*buf = root_stats'
require_source fs/zeromount.c 'zeromount_spoof_xattr'
require_source include/linux/zeromount.h 'ZEROMOUNT_IOC_GET_STATUS'
require_source fs/namei.c 'zeromount_getname_hook'
require_source fs/readdir.c 'zeromount_inject_dents64'
require_source fs/d_path.c 'zeromount_get_static_vpath'
require_source fs/proc/base.c 'zeromount_get_static_vpath'
require_source fs/stat.c 'zeromount_stat_hook'
require_source fs/statfs.c 'zeromount_spoof_statfs'
require_source fs/xattr.c 'zeromount_spoof_xattr'
require_source fs/susfs.c 'susfs_add_sus_kstat_redirect'
require_source fs/susfs.c 'susfs_add_sus_map'

[[ -d "$KSU_TREE" ]] || {
  echo "::error::KernelSU tree not found: $KSU_TREE"
  exit 1
}
for needle in \
  'ksu_susfs_ack_deprecated_external_dir' \
  'case CMD_SUSFS_SET_ANDROID_DATA_ROOT_PATH:' \
  'case CMD_SUSFS_SET_SDCARD_ROOT_PATH:'; do
  grep -RqF "$needle" "$KSU_TREE" || {
    echo "::error::ZeroMount/SUSFS external-directory compatibility is missing: $needle"
    exit 1
  }
done

# The legacy ZeroMount maps hook overlaps the pinned SUSFS show_map_vma() and caused
# a real apexd Oops on e3q. SUSFS SUS_MAP supplies map hiding, so the unsafe
# duplicate task_mmu hook must remain absent.
if grep -qF 'zeromount_spoof_mmap_metadata' "$COMMON_TREE/fs/proc/task_mmu.c"; then
  echo "::error::Unsafe duplicate ZeroMount task_mmu hook was reintroduced"
  exit 1
fi

echo "Verified ZeroMount VFS hooks, full statfs spoofing, SUSFS ${SUSFS_EXPECTED_VERSION:-pinned} bridge, and external-directory compatibility"
