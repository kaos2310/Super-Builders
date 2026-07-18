#!/bin/bash
set -euo pipefail

COMMON="${1:?kernel common tree is required}"
REPORT="${2:-${RUNNER_TEMP:-/tmp}/susfs-v2.2-procfs-audit.txt}"

TASK_MMU="$COMMON/fs/proc/task_mmu.c"
PROC_BASE="$COMMON/fs/proc/base.c"
SUSFS_C="$COMMON/fs/susfs.c"
SUSFS_H="$COMMON/include/linux/susfs.h"
SUSFS_DEF="$COMMON/include/linux/susfs_def.h"

passes=0
failures=0

mkdir -p "$(dirname "$REPORT")"
: > "$REPORT"

log() {
  printf '%s\n' "$*" | tee -a "$REPORT"
}

pass() {
  passes=$((passes + 1))
  log "[PASS] $*"
}

fail() {
  failures=$((failures + 1))
  log "[FAIL] $*"
}

require_file() {
  if [[ -f "$1" ]]; then
    pass "present: ${1#$COMMON/}"
  else
    fail "missing: ${1#$COMMON/}"
  fi
}

require_pattern() {
  local file="$1"
  local pattern="$2"
  local description="$3"

  if grep -Eq "$pattern" "$file" 2>/dev/null; then
    pass "$description"
  else
    fail "$description"
  fi
}

require_count() {
  local file="$1"
  local pattern="$2"
  local minimum="$3"
  local description="$4"
  local count

  count=$(grep -Ec "$pattern" "$file" 2>/dev/null || true)
  if (( count >= minimum )); then
    pass "$description (count=$count)"
  else
    fail "$description (count=$count, expected >= $minimum)"
  fi
}

log "SUSFS v2.2.0 Procfs/SUS_MAP source audit"
log "common tree: $COMMON"
log ""

for file in "$TASK_MMU" "$PROC_BASE" "$SUSFS_C" "$SUSFS_H" "$SUSFS_DEF"; do
  require_file "$file"
done

if (( failures > 0 )); then
  log ""
  log "Audit stopped because required files are missing."
  exit 1
fi

require_pattern "$SUSFS_H" '^#define[[:space:]]+SUSFS_VERSION[[:space:]]+"v2\.2\.0"' \
  "SUSFS reports v2.2.0"
require_pattern "$SUSFS_DEF" 'AS_FLAGS_SUS_MAP' \
  "AS_FLAGS_SUS_MAP is defined"
require_pattern "$SUSFS_C" 'susfs_add_sus_map' \
  "SUS_MAP registration path exists"
require_pattern "$SUSFS_C" 'AS_FLAGS_SUS_MAP' \
  "SUS_MAP inode/address-space flag is assigned"

# /proc/<pid>/maps, smaps and smaps_rollup are implemented in task_mmu.c.
require_count "$TASK_MMU" 'AS_FLAGS_SUS_MAP|PRE_CHECK_SUS_MAP' 5 \
  "task_mmu.c contains the complete SUS_MAP decision surface"
require_pattern "$TASK_MMU" 'show_map_vma' \
  "maps output path is present"
require_pattern "$TASK_MMU" 'show_smap|smap_gather_stats|smaps' \
  "smaps statistics path is present"
require_pattern "$TASK_MMU" 'pagemap_read' \
  "pagemap filtering path is present"
require_pattern "$TASK_MMU" 'walk_page_range' \
  "pagemap walk path is auditable"

# Current v2.2.0 fixes restrict filtering to unmounted app processes. Accept the
# current helper name and the older helper only when the app/UID guard is also
# visible in the same source tree.
if grep -Rq 'susfs_is_current_proc_umounted_app' "$TASK_MMU" "$PROC_BASE" "$SUSFS_C" "$SUSFS_H"; then
  pass "current unmounted-app process guard is integrated"
elif grep -Rq 'susfs_is_current_proc_umounted' "$TASK_MMU" "$PROC_BASE" "$SUSFS_C" "$SUSFS_H" && \
     grep -RqE 'current_uid\(\)\.val[[:space:]]*>?=[[:space:]]*10000|uid[^\n]*10000' "$TASK_MMU" "$PROC_BASE" "$SUSFS_C" "$SUSFS_H"; then
  pass "legacy helper is paired with an explicit app UID guard"
else
  fail "no valid unmounted-app process guard found"
fi

# /proc/<pid>/mem and map_files are implemented in base.c on Android 6.1.
require_count "$PROC_BASE" 'AS_FLAGS_SUS_MAP|PRE_CHECK_SUS_MAP' 2 \
  "base.c filters both remote memory and map_files"
require_pattern "$PROC_BASE" '__access_remote_vm|mem_rw' \
  "remote-memory access path is covered"
require_pattern "$PROC_BASE" 'map_files' \
  "map_files directory path is covered"

# Detect the common partial-backport failure: registration succeeds, while the
# procfs readers contain no corresponding filter.
registration_count=$(grep -Ec 'AS_FLAGS_SUS_MAP|PRE_CHECK_SUS_MAP' "$SUSFS_C" || true)
reader_count=$(( $(grep -Ec 'AS_FLAGS_SUS_MAP|PRE_CHECK_SUS_MAP' "$TASK_MMU" || true) + \
                 $(grep -Ec 'AS_FLAGS_SUS_MAP|PRE_CHECK_SUS_MAP' "$PROC_BASE" || true) ))
if (( registration_count > 0 && reader_count >= 7 )); then
  pass "registration and procfs reader integration are both present"
else
  fail "partial SUS_MAP backport detected (registration=$registration_count readers=$reader_count)"
fi

# v2.2.0 hides matching mappings instead of presenting them as anonymous VMAs.
if grep -Eq 'AS_FLAGS_SUS_MAP|PRE_CHECK_SUS_MAP' "$TASK_MMU" && \
   grep -Eq 'continue;|goto[[:space:]]+show_pad|return[[:space:]]+0' "$TASK_MMU"; then
  pass "task_mmu.c contains skip/hide control flow for SUS_MAP entries"
else
  fail "task_mmu.c lacks a visible skip/hide control flow"
fi

log ""
log "Summary: PASS=$passes FAIL=$failures"

if (( failures > 0 )); then
  log "SUSFS Procfs/SUS_MAP audit failed. Refusing to build a kernel that only accepts rules but leaves mappings visible."
  exit 1
fi

log "SUSFS Procfs/SUS_MAP audit passed."
