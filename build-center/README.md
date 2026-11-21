# SukiSU Build Center 1.2.1 · Samsung EZJB

Buildziel: **SM-S928B / S928BXXU6EZJB / S928BOXM6EZJB / EUX / Android 17 mit Android-14-GKI 6.1.162**.

## Quellen und Automatik

Die APK löst den offiziellen SukiSU-Main-Commit über die unveränderte Repository-ID 957055748 auf. Damit bleibt die Abfrage nach der Umbenennung von Ultra zu Nova gültig. Versionscode und Commitanzahl werden mit der Formel aus dem Kbuild genau dieses Commits geprüft. Ein niedrigerer Nova-Versionscode wird nicht als veralteter Ultra-Stand behandelt. Alternativ ist der offizielle Release-Kanal wählbar.

SuSFS wird unabhängig von SukiSU vom offiziellen Branch `gki-android14-6.1` abgefragt. Versionsstring und CLI stammen vom gleichen unveränderlichen Commit. Auch eine Änderung ausschließlich an SuSFS kann einen Build auslösen.

Der Controller für dieses Firmwareziel ist `codex/build-center-ezjb-auto-20261122`. Eine gespeicherte alte EZJ1-Automatik oder ein entfernter versionsgebundener Branch wird nach Prüfung auf diesen Controller umgestellt. Fremde Repositorys und ungültige Controller-Hashes werden nicht stillschweigend ersetzt.

App und CI binden beide Quellen, Versionsformel, Update-Kanal und Controller-SHA in einem Quellenauftrag. Bewegt sich eine Quelle zwischen App-Prüfung und CI-Auflösung, bricht der Auftrag ab und verlangt eine erneute Prüfung. Ein Auftrag kann dadurch nicht unbemerkt andere Quellen bauen.

Bei aktiviertem „automatisch prüfen und bauen“ startet die verbundene App neue Quellpaare selbstständig. Laufende Builds, passende veröffentlichte Ergebnisse, gesendete Aufträge und eine 24-Stunden-Wartezeit nach einem Fehler verhindern wiederholte Aufträge. Der manuelle Neubau mit Vorschau bleibt verfügbar.

Auf dem Default-Branch wird nur `integration/main-automatic.yml` als `.github/workflows/build-center.yml` installiert. Dieser kleine Controller prüft zweimal pro Stunde und startet den vollständigen Worker auf dem oben genannten Branch. Die Automatik benötigt daher keine dauerhaft geöffnete APK. GitHub kann geplante Läufe verzögern. App-Aufträge benötigen einen auf das Repository beschränkten Token mit Actions-Schreibrecht und Contents-Leserecht; öffentliche Abfragen und Releases können API-Limits unterliegen.

## Firmware und Freigabeprüfungen

Das aktive Profil unter `ci/firmware/ezjb/` stammt aus den geprüften EZJB-Odin-Archiven. Archividentitäten, Stock-Image-Hashes, Zeitstempel und 5470 Stock-Import-CRCs werden mitgeführt. Alle 2485 Einträge der bisherigen strengen Samsung-Baseline stimmen überein. Der Quellpfad bleibt der geprüfte Samsung-Port auf AOSP 6.1.162; ein vollständiger unabhängiger Abgleich mit exaktem Samsung-EZJB-OSS ist nicht nachgewiesen.

Userspace, SuSFS, ZeroMount, Kernel-Link, Strict KMI, DLKM-CRCs, HIDDEN_NAME-v2 und Veröffentlichungsprüfungen bleiben vorgeschrieben. Bei inkompatiblen zukünftigen Upstream-Änderungen wird keine fertige ZIP behauptet. Eine universelle automatische Anpassung beliebiger zukünftiger Kernel- oder Modul-ABIs ist nicht möglich.

Für das unterstützte SuSFS-2.4.0-ABI werden die bisherigen ReSuSFS- und Guard6.13/BRENE75-Zusatzpakete gebaut. Bei anderen SuSFS-Versionen wird nur das passende offizielle ARM64-Werkzeug zusätzlich angeboten, sofern alle Kernelprüfungen bestehen. Der separat veröffentlichte statische EZJB/Nova-Build mit BRENE76 bleibt erhalten. Diese App-Anpassung installiert oder ersetzt keine Root-Module auf dem Telefon.

## Downloads und Geräteprüfung

Die APK, der lokale Webserver und die Windows-Quelle akzeptieren ausschließlich das EZJB/EUX-Ziel. Vor der Bereitstellung müssen veröffentlichte SHA256, tatsächlicher Image-Hash, `FIRMWARE-TARGET.json`, AnyKernel3 und Strict-KMI-Nachweis zusammenpassen. Ältere EZJ1- oder EZIF-Kernel werden auch bei gültiger äußerer Prüfsumme abgewiesen.

Der reine statische Browser öffnet den GitHub-Download. Die zusätzliche Inhaltsprüfung erfolgt in der Android-App oder im lokalen Web-/Windows-Server. Kernel-ZIPs werden gespeichert; die App flasht keinen Kernel und startet das Gerät nicht neu.

Ein erfolgreicher GitHub-Build ist kein Boot- oder Runtime-Nachweis auf dem S24. Die Abnahme dieser Änderung prüft die installierte Firmware, App-Abfragen, Controller-Migration, Build-Auftrag und ZIP-Download. Geräte-Flash und Kernel-Runtime-Tests gehören nicht zu dieser Änderung.

Der frühere angepasste Root-Manager bleibt als historischer EZJ1/41168-Stand unter `manager/` dokumentiert. Er wird nicht als aktueller EZJB/Nova-Manager angeboten. Die Signaturprüfung dieser eigenen App-Identität und des offiziellen Managers bleibt erhalten.

## Reproduzierbarkeit

`ci/generate_workflows.py` erzeugt die fünf wiederverwendbaren Workflows aus dem festgelegten Baseline-Commit und dem gemessenen EZJB-Profil. `tools/update_controller_manifest.py` synchronisiert die Integrationskopien und bindet Workflow und Resolver an ihre SHA256. APK-Version 1.2.1 verwendet VersionCode 8 und denselben bestehenden Signierschlüssel wie die installierte 1.2.0.
