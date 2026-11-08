#!/system/bin/sh
SKIPUNZIP=1
[ "$KSU" = true ] && [ "$KSU_SUKISU" = true ] || abort "SukiSU Manager erforderlich"
[ "$(uname -m)" = aarch64 ] || abort "Dieses Modul benötigt ARM64"
KSUD=/data/adb/ksud
[ -x "$KSUD" ] || KSUD=/data/adb/ksu/bin/ksud
VERSION=$("$KSUD" susfs version 2>/dev/null) || abort "SUSFS-Version konnte nicht gelesen werden"
[ "$VERSION" = v2.4.0 ] || abort "Zuerst den passenden SUSFS-2.4.0-Kernel installieren und booten; gefunden: $VERSION"
unzip -o "$ZIPFILE" -d "$MODPATH" >&2 || abort "ZIP konnte nicht entpackt werden"
set_perm_recursive "$MODPATH" 0 0 0755 0644
set_perm_recursive "$MODPATH/bin" 0 0 0755 0755
for SCRIPT in "$MODPATH"/*.sh "$MODPATH/META-INF/com/google/android/update-binary"; do
    [ ! -f "$SCRIPT" ] || set_perm "$SCRIPT" 0 0 0755
done
"$MODPATH/bin/zm" integrity || abort "Paket-Prüfsummen stimmen nicht überein"
"$MODPATH/bin/zm" susfs-compat --check || abort "SUSFS-2.4.0-ABI-Prüfung fehlgeschlagen"

# All persistent user configuration lives outside the staged module directory.
# Never reset config, owner selection, rules, BRENE options or existing switches.
STATE=/data/adb/zeromount
umask 077
mkdir -p "$STATE/switches" "$STATE/logs" || abort "ZeroMount-Datenordner konnte nicht angelegt werden"
for MASTER in susfs brene; do
    [ -e "$STATE/switches/$MASTER.enabled" ] || printf 'false\n' > "$STATE/switches/$MASTER.enabled"
done
if [ ! -f "$STATE/config.toml" ]; then
    "$MODPATH/bin/arm64-v8a/zm-native-core" config set susfs.enabled false >/dev/null || abort "Grundkonfiguration fehlgeschlagen"
fi
ui_print "ZeroMount Guard6.13 / BRENE75 / SUSFS2.4.0 / SukiSU41165"
ui_print "Bestehende Konfiguration, SUSFS-Zuständigkeit und Regeln bleiben erhalten."
ui_print "Nach dem Modulupdate neu starten."
