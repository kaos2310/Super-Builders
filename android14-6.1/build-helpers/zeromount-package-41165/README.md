# ZeroMount Guard6.13 / BRENE75 / SUSFS 2.4.0 / SukiSU 41165

Dieses ARM64-Modul wird über den SukiSU-Manager installiert. Es ist keine
Kernel-/Recovery-ZIP. Zuerst den passenden SukiSU41165-/SUSFS2.4.0-Kernel
installieren und booten, danach diese Modul-ZIP installieren und neu starten.

Basis ist der ausgelesene vollständige 41159-Modulstand mit Guard6.13,
BRENE75, Hauptschaltern, externer SUSFS-Zuständigkeit, Patchdatum-Policy,
BootGuard, DroidSpaces, persistenten eigenen Regeln und Writer-Adaptern.
Gerätekonfiguration, Laufzeitcaches und fremde gestagte Dateien sind nicht
enthalten. Bestehende Einstellungen außerhalb des Modulordners bleiben erhalten.

Der originale Guard6.13-Quellstand war lokal nicht auffindbar. Die Anpassung
des nativen Kerns ist deshalb ausdrücklich ein exakter, hashgebundener
Kompatibilitätspatch seiner SUSFS-Versionsprüfung. Der offizielle SUSFS2.4.0-
Release ändert gegenüber dem vorhandenen aktuellen Funktionsstand ausschließlich
die Versionskennung; das ABI bleibt gleich. Der Patch und sein tatsächlicher
Versions-Gate-Test sind separat dokumentiert. Ein Neubau des gesamten nativen
ZeroMount-Kerns aus Quellen wird nicht behauptet.

Settings enthält einen direkten SUSFS-&-BRENE-Einstieg. Die Übersicht und
Editoren verwenden gemeinsame Navigation und Darstellung. Laufzeitänderungen
verwenden den mitgelieferten freistehenden Runtime-v1-Helfer mit Feature-/ABI-
Prüfung, Hauptschaltern, Generation-CAS und bestätigtem Readback. Ein aktiver
externer Verwalter wie ReSuSFS sperrt parallele ZeroMount-SUSFS-Schreibzugriffe.
Neue Schalter werden nicht automatisch freigegeben; bestehende Regeln bleiben
gespeichert. Der schwebende Link und veraltete ReSukiSU-/BRENE-Beschriftungen
sind entfernt. Weiter unterstützte Funktionen bleiben erhalten.

Alle Paketdateien und das ZIP haben SHA-256-Nachweise. Die Modulinstallation
prüft Architektur, SUSFS2.4.0, Paketintegrität und den nativen ABI-Gate. Ein
erfolgreicher Paketbuild ersetzt keinen Boot-/Funktionstest des installierten
Moduls auf dem Telefon.
