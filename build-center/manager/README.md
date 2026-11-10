# SukiSU EZJ1 Root-Manager

Eigene Anpassung von SukiSU Ultra 41168, Quell-Pin `674aa00c18adc3d7ef4069c03018d6194230865a`.
Paket: `com.kaoslab.sukisu.manager`; ARM64; Release-Build mit Android-17-Ziel.
Der offizielle Manager `com.sukisu.ultra` kann parallel installiert bleiben.

Die neue Karte **SuSFS-Laufzeit** steht in beiden vorhandenen Oberflächen auf der Startseite.
Sie liest ReSuSFS Runtime-ABI v1 und steuert UID-Filter, HIDDEN_NAME, Unicode-Filter und
Symbol-Hiding. Änderungen gelten sofort bis zum nächsten Boot. Veraltete Generationen
werden abgelehnt; ein fehlgeschlagener Schreibauftrag wird nicht automatisch wiederholt.
Buildziel und tatsächlich gelesene Geräte-Firmware werden separat angezeigt.

Updates für dieses Paket kommen ausschließlich aus den passenden öffentlichen
`SukiSU_EZJ1_*_*-arm64-v8a-release.apk`-Assets in `kaos2310/Super-Builders`.
Der Installer prüft Paketkennung, Version und das bereits installierte Signierzertifikat.

## Erstmalige Freigabe

Ein anderes Signierzertifikat erfordert eine eigene Manager-Freigabe im vorhandenen,
vertrauenswürdigen SukiSU. Eine bloße Installation der APK erteilt keine Verwaltungsrechte.
Die offizielle Signaturprüfung des Kernels bleibt erhalten. Nach bewusster Freigabe durch
den Gerätebesitzer kann der vorhandene Root-Zugang diese exakte Identität registrieren:

```sh
su -c '/data/adb/ksud manager list'
su -c '/data/adb/ksud manager add com.kaoslab.sukisu.manager 744 28ef122baa66fe3fa7d49ce2ca4d652b16c22cd51d719d8e606a0ad0b8ee2d36'
```

Die dynamische Manager-Verwaltung muss bereits aktiviert sein oder gesondert bewusst
aktiviert werden. Vorher ihre vorhandene Konfiguration sichern. Die Registrierung lässt
sich mit `ksud manager remove com.kaoslab.sukisu.manager` wieder entfernen.
Die APK oder ein Build-Center-Download führt diese Freigabe nicht selbst aus.

## Nachbauen

Das vollständige öffentliche Quell-ZIP enthält die exakten SukiSU- und KernelPatch-Quellen,
die Anpassung als Patch und die drei mit Prüfsummen belegten nativen Eingaben. KernelPatch
ist auf `1c5b608916357ac86a94cc736e235db1fac4a29d` / ABI2 festgelegt. ksud ist UAPI6 und
stammt aus dem zugehörigen gepinnten Actions-Userspace-Build. Diese Dateien werden im APK
bytegenau erhalten; der spezielle Build lädt keine veränderlichen KPM-Werkzeuge von `main`.

Benötigt werden JDK21 oder neuer, Android SDK37.0, Build-Tools37.0.0, NDK29.0.14206865
und CMake3.22.1. Im entpackten Quellpaket `build.ps1 -AndroidSdk <SDK-Pfad>` ausführen.
Für einen vollständigen Testlauf unter Linux `:app:testReleaseUnitTest` ohne `--tests`
aufrufen; einige Dateisystemtests setzen Unix-Dateirechte und Dateinamen voraus.
Ein eigener Signierschlüssel muss selbst bereitgestellt werden. Private Schlüssel sind
weder im Repository noch in den veröffentlichten Paketen enthalten.
