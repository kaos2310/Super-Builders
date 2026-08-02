#!/bin/bash
set -euo pipefail

COMMON_TREE="${1:?common kernel tree}"
MAKEFILE="$COMMON_TREE/mm/Makefile"
STUB="$COMMON_TREE/mm/kasan_kmi_compat.c"
HW_TAGS="$COMMON_TREE/mm/kasan/hw_tags.c"
ENTRY='obj-y += kasan_kmi_compat.o'

for required in "$MAKEFILE" "$HW_TAGS"; do
  [[ -f "$required" ]] || {
    echo "::error::Required kernel source file is missing: $required"
    exit 1
  }
done

[[ "$(grep -cFx 'DEFINE_STATIC_KEY_FALSE(kasan_flag_enabled);' "$HW_TAGS" || true)" -eq 1 ]] || {
  echo "::error::Unexpected kasan_flag_enabled definition in mm/kasan/hw_tags.c"
  exit 1
}
[[ "$(grep -cFx 'EXPORT_SYMBOL(kasan_flag_enabled);' "$HW_TAGS" || true)" -eq 1 ]] || {
  echo "::error::Unexpected kasan_flag_enabled export class in mm/kasan/hw_tags.c"
  exit 1
}

cat > "$STUB" <<'STUB_EOF'
// SPDX-License-Identifier: GPL-2.0
#include <linux/export.h>
#include <linux/kconfig.h>
#include <linux/static_key.h>

#if !IS_ENABLED(CONFIG_KASAN_HW_TAGS)
DEFINE_STATIC_KEY_FALSE(kasan_flag_enabled);
EXPORT_SYMBOL(kasan_flag_enabled);
#endif
STUB_EOF

ENTRY_COUNT="$(grep -cFx "$ENTRY" "$MAKEFILE" || true)"
if [[ "$ENTRY_COUNT" -eq 0 ]]; then
  TMP="$(mktemp "$COMMON_TREE/mm/Makefile.kasan-kmi.XXXXXX")"
  trap 'rm -f "$TMP"' EXIT
  awk -v entry="$ENTRY" '
    !inserted && index($0, "obj-$(CONFIG_KASAN)") && index($0, "kasan/") {
      print entry
      inserted = 1
    }
    { print }
    END {
      if (!inserted)
        exit 42
    }
  ' "$MAKEFILE" > "$TMP" || {
    echo "::error::Could not place the always-built KASAN KMI object in mm/Makefile"
    exit 1
  }
  mv "$TMP" "$MAKEFILE"
  trap - EXIT
elif [[ "$ENTRY_COUNT" -ne 1 ]]; then
  echo "::error::Duplicate KASAN KMI object entries in mm/Makefile"
  exit 1
fi

grep -qxF '#if !IS_ENABLED(CONFIG_KASAN_HW_TAGS)' "$STUB"
grep -qxF 'DEFINE_STATIC_KEY_FALSE(kasan_flag_enabled);' "$STUB"
grep -qxF 'EXPORT_SYMBOL(kasan_flag_enabled);' "$STUB"
[[ "$(grep -cFx "$ENTRY" "$MAKEFILE" || true)" -eq 1 ]]

echo "Installed always-built KASAN-off KMI compatibility stub:"
echo "  $STUB"
echo "  $ENTRY"
