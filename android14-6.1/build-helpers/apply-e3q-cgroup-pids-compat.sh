#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common kernel tree is required}"

[[ -d "$COMMON_TREE" ]] || {
  echo "::error::Missing common kernel tree: $COMMON_TREE"
  exit 1
}

# Do not patch Samsung's cgroup core to fake compatibility. The final Kleaf
# fragment owns CONFIG_CGROUP_PIDS: runtime-compat Droidspaces builds enable
# the controller, while the strict Samsung KMI path explicitly disables it
# later to preserve the stock DLKM structure layout.
echo "Samsung e3q: no cgroup core compatibility patch applied; final KMI mode controls CONFIG_CGROUP_PIDS"
