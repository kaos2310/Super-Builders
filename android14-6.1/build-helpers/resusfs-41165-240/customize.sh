#!/system/bin/sh
# The module manager extracts this ZIP. Upgrade preserves all existing profiles.
ui_print '- ReSuSFS / SUSFS 2.4.0 / Runtime v1'
[ "$KSU" = true ] || abort 'KernelSU / SukiSU required'
[ "$(getprop ro.product.cpu.abi)" = arm64-v8a ] || abort 'ARM64 only'
set_perm_recursive "$MODPATH" 0 0 0755 0644
for file in "$MODPATH"/*.sh "$MODPATH"/bin/*; do [ ! -f "$file" ] || set_perm "$file" 0 0 0755; done
version=$("$MODPATH/bin/ksu_susfs" show version 2>/dev/null) || abort 'SUSFS version query failed'
case "$version" in v2.3.0|v2.4.0) ;; *) abort "Unaudited SUSFS version: $version";; esac
PERSISTENT_DIR=/data/adb/ReSuSFS
if [ ! -d "$PERSISTENT_DIR" ]; then
    mkdir -p "$PERSISTENT_DIR" || abort 'Cannot create ReSuSFS settings directory'
    cp -R "$MODPATH/configs/." "$PERSISTENT_DIR/" || abort 'Cannot create initial upstream defaults'
    mkdir -p "$PERSISTENT_DIR/.webui_config" || abort 'Cannot create initial UI directory'
    cp "$MODPATH/custom.css" "$PERSISTENT_DIR/.webui_config/custom.css" || abort 'Cannot create initial upstream UI style'
    set_perm_recursive "$PERSISTENT_DIR" 0 0 0700 0600
fi
# No config replacement, owner transfer, global CLI overwrite or runtime SET.
ui_print "- Kernel reports $version; existing configuration retained"
ui_print '- New controls remain unchanged until explicitly selected'
