#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common kernel tree is required}"
SOURCE="$COMMON_TREE/kernel/cgroup/cgroup.c"
PYTHON_BIN="${PYTHON_BIN:-python3}"

[ -f "$SOURCE" ] || {
  echo "::error::Missing cgroup source: $SOURCE"
  exit 1
}

"$PYTHON_BIN" - "$SOURCE" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")

original = """\tif (tsk->flags & PF_KTHREAD)\n\t\ttrace_android_rvh_cgroup_force_kthread_migration(tsk, dst_cgrp, &force_migration);\n"""
replacement = """\t/*\n\t * Samsung e3q vendor modules are built against the stock cgroup layout\n\t * without CONFIG_CGROUP_PIDS. Enabling it adds a cgroup subsystem slot\n\t * before cgroup->root, so the prebuilt sched_walt hook reads root from\n\t * the wrong offset and panics at boot. Keep the PIDs controller, but let\n\t * the core migration safety checks below handle kthreads without calling\n\t * the layout-incompatible vendor override.\n\t */\n\tif ((tsk->flags & PF_KTHREAD) && !IS_ENABLED(CONFIG_CGROUP_PIDS))\n\t\ttrace_android_rvh_cgroup_force_kthread_migration(tsk, dst_cgrp, &force_migration);\n"""

if replacement in text:
    print("Samsung e3q cgroup PIDs compatibility guard already present")
elif text.count(original) == 1:
    path.write_text(text.replace(original, replacement, 1), encoding="utf-8")
    print("Applied Samsung e3q cgroup PIDs compatibility guard")
else:
    raise SystemExit(
        "Expected exactly one cgroup kthread vendor-hook call; source drifted"
    )
PY

grep -Fq 'PF_KTHREAD) && !IS_ENABLED(CONFIG_CGROUP_PIDS)' "$SOURCE" || {
  echo "::error::Samsung e3q cgroup PIDs compatibility guard was not retained"
  exit 1
}
