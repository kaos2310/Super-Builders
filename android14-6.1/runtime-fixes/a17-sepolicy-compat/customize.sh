#!/system/bin/sh
set -eu

ui_print "- Android 17 ReSukiSU SEPolicy compatibility"
ui_print "- ZeroMount/SUSFS are not modified"

patch_zygisk() {
  file=/data/adb/modules/zygisksu/sepolicy.rule
  [ -f "$file" ] || {
    ui_print "- Zygisk Next sepolicy.rule not found; skipping"
    return 0
  }

  count=$(grep -Ec '^[[:space:]]*(allow|dontaudit|auditallow|deny)[[:space:]]+[^[:space:]]+[[:space:]]+nsfs([[:space:]:]|$)' "$file" || true)
  case "$count" in
    0)
      ui_print "- Zygisk Next: nsfs rules already absent"
      ;;
    2)
      cp -af "$file" "$file.a17-resukisu.bak"
      awk '!($1 ~ /^(allow|dontaudit|auditallow|deny)$/ && $3 == "nsfs")' "$file.a17-resukisu.bak" > "$file"
      left=$(grep -Ec '^[[:space:]]*(allow|dontaudit|auditallow|deny)[[:space:]]+[^[:space:]]+[[:space:]]+nsfs([[:space:]:]|$)' "$file" || true)
      [ "$left" -eq 0 ] || abort "Zygisk Next nsfs policy removal verification failed"
      chmod 0644 "$file"
      ui_print "- Zygisk Next: removed exactly 2 unsupported nsfs rules"
      ;;
    *)
      abort "Unexpected Zygisk Next nsfs rule count: $count (expected 0 or 2)"
      ;;
  esac
}

patch_avf() {
  file=/data/adb/modules/avf_gunyah_runtime/sepolicy.rule
  [ -f "$file" ] || {
    ui_print "- AVF/Gunyah runtime sepolicy.rule not found; skipping"
    return 0
  }

  old='allow virtualizationservice self:capability sys_resource;'
  new='allow virtualizationservice virtualizationservice:capability sys_resource;'
  old_count=$(grep -Fxc "$old" "$file" || true)
  new_count=$(grep -Fxc "$new" "$file" || true)

  if [ "$old_count" -eq 1 ] && [ "$new_count" -eq 0 ]; then
    cp -af "$file" "$file.a17-resukisu.bak"
    sed -i "s|^${old}$|${new}|" "$file"
    [ "$(grep -Fxc "$new" "$file" || true)" -eq 1 ] || abort "AVF self-target replacement verification failed"
    [ "$(grep -Fxc "$old" "$file" || true)" -eq 0 ] || abort "AVF self-target rule still present"
    chmod 0644 "$file"
    ui_print "- AVF/Gunyah: expanded self -> virtualizationservice"
  elif [ "$old_count" -eq 0 ] && [ "$new_count" -eq 1 ]; then
    ui_print "- AVF/Gunyah: self target already expanded"
  else
    abort "Unexpected AVF virtualizationservice rule layout (old=$old_count new=$new_count)"
  fi
}

patch_zygisk
patch_avf

ui_print "- Done. Reboot required for the corrected rules to be loaded."
ui_print "- Reinstall this compatibility module after updating Zygisk Next or AVF/Gunyah."
