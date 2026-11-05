# ZeroMount Guard6.13 mit BRENE 0.0.75 für SukiSU 41150

Dieses Paket baut auf den beiden unveränderten, vom Benutzer gelieferten ZIPs
auf. Die Eingabe-SHA256-Werte sind in package.py und im Paketmanifest gebunden.
Guard6.13, BootGuard2, UIDGate2, DroidSpaces-VFS, OPEN_REDIRECT-Regelverwaltung,
der native ARM64-Kern und die vorhandenen Writer-Adapter bleiben erhalten.
Das ist eine zusätzliche BRENE75-Integration, keine unveränderte Installation
des eigenständigen BRENE-Moduls. Dessen Boot- und Löschskripte werden nicht
übernommen oder ausgeführt. Die Autoren sind in der Eingabequittung genannt.

Die sieben Schalter sind: 64-KiB-Logpuffer, Stock-Hosts, libstagefright-Sicht,
Lineage-Dateisichten, Phantom-Prozessoption, KernelSU-Verzeichnissicht und
Priority-UID-Filter für Drittanbieter-Apps. Bestehende Einstellungen bleiben
unter /data/adb/zeromount/brene71/options erhalten. Die zwei neuen Schalter
starten aus. Der vorhandene Logpuffer-Standard bleibt erhalten.

Die neue Verzeichnisfunktion verwendet ausschließlich SuSFS add-sus-path-loop
für die sechs Paketnamen aus BRENE75. Sie löscht weder Termux-/HMA-Daten noch
andere App-Verzeichnisse. Sichtbarkeit hängt weiterhin von Kernel-UIDGate und
SUSFS-Markierungen ab. Der neue Drittanbieterfilter ersetzt die gesamte
Priority-UID-Liste beim Boot; nicht gleichzeitig mit einer eigenen Manager-
Liste verwenden. Das Paket fragt Features exakt ab und lehnt fehlende Features
ab. Neu installierte Drittanbieter-Apps werden beim nächsten Anwenden erfasst.

Neue Optionen werden erst beim nächsten Boot angewandt. Das Speichern löst
keinen Neustart aus. Bereits registrierte Regeln werden im laufenden Boot
nicht rückgängig gemacht. Ein externes SUSFS-Modul behält die Zuständigkeit;
die neuen Funktionen verweigern dann konkurrierende Änderungen.

SukiSU 41150 verwendet die Befehle `susfs version`, `susfs features`,
`susfs add-open-redirect`, `susfs add-sus-path-loop` und
`susfs set-priority-uid-filter`. Die alte Standalone-Syntax `susfs show ...`
wird im gelieferten Installer und UIDGate-Wrapper korrigiert. Die native
`susfs-compat --check`-Prüfung bleibt aktiv. Der Begleitkernel benötigt
CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER=y zusätzlich zu den bisherigen SUSFS-,
UIDGate-, ZeroMount- und OPEN_REDIRECT-Optionen.

Die alten BRENE69-Property-Schalter bleiben als bestehende Benutzerfunktion
zugänglich. BRENE75 entfernt einige dieser Standalone-Defaults; diese Migration
überschreibt keine vorhandenen Benutzerwerte. Gemeldete Patchdaten installieren
keine Sicherheitsupdates und Lock-Properties ändern keinen Bootloaderzustand.

Die Paketprüfungen bestätigen CRCs, alle Prüfsummen, den unveränderten nativen
Kern und die Herkunft der Eingaben. Adapter-/CLI-/WebUI-Tests laufen isoliert
mit simulierten Android-Systemgrenzen. Installation, Geräteboot, echte Mounts
und Laufzeitverhalten auf dem Telefon sind damit noch nicht nachgewiesen.
