# ZeroMount Guard6.13 mit BRENE 0.0.71 und SukiSU 41013

Grundlage ist das vom Benutzer gelieferte Guard6.13/BRENE69/UIDGate2/BootGuard2-ZIP.
Der native ARM64-Kern bleibt byteidentisch (`1a0b2524...`); UIDGate2, BootGuard2,
DroidSpaces VFS, Writer-Adapter, Emoji, LKMs und die bisherigen Regelverwaltungen
bleiben erhalten. Der Begleitkernel basiert auf dem erfolgreichen Run 39061619013.
Ziel: S928BXXU6EZIF/EUX, offizielles SukiSU 41013, native UAPI6, SUSFS v2.3.0.
Der passende Manager ist SukiSU (`com.sukisu.ultra`).

Die zusätzliche BRENE-71-Seite enthält den 64-KiB-Logpuffer, optionale Stock-Hosts
über OPEN_REDIRECT, libstagefright-/Lineage-Dateisichten und die Android-Option
für Phantom-Prozesse. Die letzten vier Schalter sind zunächst aus. Eine aktivierte
leere Dateisicht kann Apps beeinträchtigen. Änderungen werden erst beim nächsten
Boot angewandt. Bereits registrierte Kernel-Regeln bleiben bis zum Neustart aktiv.
Die vorhandenen persistenten OPEN_REDIRECT- und SUSFS-Regel-Editoren dienen auch
für eigene Umleitungen. Die Empfehlung UID Filter ist nur verlinkt.

Der vorhandene Property-Writer wird über denselben ZeroMount-Dispatcher erst nach
Boot-Abschluss ausgeführt, damit ro.crypto.state nicht vor vold/init gesetzt wird.
Die bestehende System-/Vendor-Patchdatum-Auswahl erhält anschließend die BRENE-71-
Monatsregel: vor dem 5. Tag der Vormonat, einschließlich Jahreswechsel. Die
Datumsrechnung behandelt 08/09 dezimal und verwirft unplausible Uhren. Gemeldete
Patchdaten installieren keine Sicherheitsupdates. Native Gruppenabschaltung und
die Zuständigkeit externer SUSFS-Module werden respektiert.

Es werden keine Standalone-BRENE-Bootskripte importiert. Weitere Root-Module werden
nicht automatisch installiert oder deaktiviert. Die bisherigen Writer-Adapter
arbeiten weiterhin nur mit ihren bereits geprüften exakten Peer-Versionen.
Das ursprüngliche Manifest steht als historische Datei im Paket; es beschreibt
keinen Gerätetest dieses neuen Pakets. Neue Paketidentität und Hashes stehen in
build-manifest.json. Die Installer-Prüfung verlangt SukiSU und SUSFS v2.3.0.

Reproduktion: package.py benötigt beide unveränderten Eingabe-ZIPs und deren
bei der Inventarisierung erfasste SHA256-Werte. Weder Skripte aus den Eingaben
noch Android-Binaries werden auf dem PC ausgeführt. test.py prüft den tatsächlich
ausgelieferten Adapter mit simulierten Android-Befehlen; das ersetzt keinen
Installations-, Boot- oder Laufzeittest auf dem Telefon.

Das separat im Kernel-Run erzeugte ZeroMount-compat-Artefakt ist der Basisdetektor.
Das vollständige angepasste Guard6.13/BRENE71-ZIP wird separat bereitgestellt.
