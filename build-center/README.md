# SukiSU Build Center 1.1.1 · Samsung EZJ1

Deutsche App für Android, Windows und den lokalen Browser. Das Buildziel ist **SM-S928B / S928BXXS6EZJ1 / EUX / Android 17 mit Android 14-GKI 6.1.162**.

| Variante | Datei | Start |
| --- | --- | --- |
| Build Center für Android ab 10 | `SukiSU-Build-Center-1.1.1.apk` | Als Update installieren; bestehende Einstellungen bleiben erhalten |
| Windows 11 x64 | `SukiSU-Build-Center-1.1.1.exe` | Portable EXE öffnen; Microsoft Edge wird als App-Fenster verwendet |
| Lokale Web-App | `SukiSU-Build-Center-Web-1.1.1.zip` | Entpacken und `Start-Web.cmd` starten |
| Web auf Linux/macOS | Quellpaket | Python 3.11 oder neuer: `python3 desktop.py --web` |
| Zusätzlicher SukiSU-Root-Manager | `SukiSU_EZJ1_v4.3.0-r2-runtime1_41168-arm64-v8a-release.apk` | Parallel zum offiziellen Manager installieren; separate bewusste Manager-Freigabe erforderlich |

Windows und die lokale Web-App binden ausschließlich `127.0.0.1`. Die EXE enthält die benötigte Python-Laufzeit. Nach Schließen der Oberfläche endet der Server nach ungefähr drei Minuten; `--stay` hält ihn geöffnet. Eine PWA-Installation der Web-Oberfläche ist möglich.

## GitHub-Verbindung und Ablauf

Voreingestellt sind `kaos2310/Super-Builders`, Branch `main` und der neueste offizielle SukiSU-Entwicklungsstand. Alternativ kann der aktuelle offizielle Release-Tag gewählt werden. Für den manuellen Build-Start benötigt ein auf dieses Repository beschränkter Token **Actions: Read and write** und **Contents: Read**. Öffentliche Quellprüfungen und Release-Downloads funktionieren ohne Token, abhängig von den GitHub-/GitLab-API-Limits.

In das Feld **Workflow-Branch** gehört ein vorhandener Branch wie `main`, kein GitHub-Benutzername. Version 1.1.1 prüft diesen Wert bei der Verbindungsprüfung und erneut vor jedem Build-Auftrag. Ein ungültiger Wert wird verständlich angezeigt und deaktiviert den Startknopf. Der Bestätigungsdialog zeigt zusätzlich Repository und Workflow-Branch. Änderungen an den Verbindungsfeldern müssen erneut geprüft werden.

Der Token bleibt in Web und Windows im Arbeitsspeicher. Android speichert ihn nur auf ausdrücklichen Wunsch verschlüsselt im Android Keystore. Bei geöffneter App werden die Quellen alle 15 Minuten geprüft. Der Actions-Zeitplan prüft unabhängig davon stündlich bei Minute 17. GitHub kann geplante Läufe verzögert ausführen.

1. Offizielle SukiSU- und SuSFS-Quellen auf vollständige Commit-IDs auflösen und die Versionsformel kontrollieren.
2. Die gemessenen EZJ1-Firmwaredaten, das Geräteprofil und die unveränderte strenge Samsung-CRC-Baseline prüfen.
3. Updates integrieren und Kernel, ARM64-Userspace, ZeroMount-Kompatibilität und ReSuSFS bauen.
4. Quell-, Konfigurations-, KMI-/DLKM-/CRC-, KPM- und Paketprüfungen ausführen.
5. Bei Erfolg die echte AnyKernel3-ZIP, das passende ReSuSFS-Modul, SuSFS-Quellen, Build-Plan und Prüfsummen öffentlich bereitstellen. Kernel-Releases bleiben bis zur gesonderten Geräteprüfung als Prerelease gekennzeichnet.

Bereits veröffentlichte identische Quellpaare werden übersprungen. Nach einem Fehlschlag gilt für dieselbe Quellkombination eine 24-Stunden-Wartezeit; ein ausdrücklich gewählter Neubau übergeht diese Wartezeit und erhält einen eigenen Release-Tag. Neue Quellen müssen weiterhin alle Prüfschritte bestehen.

## Downloadprüfung

Die neue Oberfläche bietet nur Kernel für `S928BXXS6EZJ1-EUX` an. Android und der lokale Web-/Windows-Server kontrollieren die veröffentlichte SHA256, entpacken Actions-Artefakte und prüfen die echte Kernel-ZIP. `FIRMWARE-TARGET.json` muss das EZJ1/EUX-Profil und den Hash des tatsächlich enthaltenen `Image` belegen. AnyKernel3- und Strict-KMI-Nachweise sind erforderlich. Ein EZIF-Paket wird dadurch auch bei ansonsten gültiger äußerer Prüfsumme abgelehnt.

Der reine statische Browser öffnet den GitHub-Download; die zusätzliche lokale Inhaltsprüfung erfordert die Android-App oder den lokalen Server. Kernel-/ReSuSFS-ZIPs werden zum Speichern bereitgestellt. APK-Downloads öffnen nach Prüfung den Android-Paketinstaller; Kernel werden durch das Build Center nicht geflasht.

Die angepasste Manager-APK wird anhand ihrer eigenen Paketkennung und ihres exakten Zertifikats akzeptiert. Der offizielle SukiSU-Manager behält seine eigene Signaturprüfung. Beide Identitäten werden getrennt geprüft.

## Root-Manager und SuSFS-Runtime

Der zusätzliche **SukiSU EZJ1**-Manager verwendet den passenden SukiSU 41168/UAPI6-Userspace und KPM 0.14.0/ABI2. Auf beiden bestehenden Startseiten ergänzt die Karte **SuSFS-Laufzeit** vier sofort wirksame Schalter:

- UID-Filter;
- verborgene Namen in Verzeichnislisten (HIDDEN_NAME-v2);
- Unicode-Filter;
- Kernel-Symbole verbergen.

Die App zeigt Buildziel und echte Geräte-Firmware separat. Sie prüft Runtime-ABI, unterstützte Bits und die vom Kernel gelieferte Generation. Ein veralteter Schaltauftrag wird abgewiesen und nicht automatisch wiederholt. Die Änderungen gelten bis zum nächsten Neustart; gespeicherte ReSuSFS-Einstellungen werden dabei nicht überschrieben.

Die erstmalige Root-Manager-Freigabe erfolgt bewusst durch den Gerätebesitzer über einen bereits vertrauenswürdigen Zugang. Anleitung, Rücknahme und vollständige Quell-/Buildinformationen stehen in [manager/README.md](manager/README.md). Private Schlüssel sind in keinem Paket enthalten.

## Gemessenes Firmwareprofil und Prüfumfang

Alle sechs gelieferten Odin-Archive wurden vollständig per SHA256 und Odin-Tar-MD5 geprüft. Die extrahierte EZJ1-Stock-Konfiguration stimmt bytegenau mit der verwendeten geprüften Konfiguration überein. Aus882Moduldateien wurden 5470 eindeutige Import-CRCs geprüft; alle 2485 Einträge der strengen Baseline stimmen überein. Die Herkunft der Baseline bleibt unverändert dokumentiert.

Der Build verwendet den bestehenden geprüften Samsung-Port auf AOSP6.1.162. Ein eigenständiger vollständiger Samsung-EZJ1-OSS-Abgleich ist nicht nachgewiesen; Stock-Konfiguration, Firmwareidentität und Modul-CRCs wurden aus den gelieferten Archiven gemessen. `CONFIG_CGROUP_PIDS=n` und `CONFIG_CFS_BANDWIDTH=n` bleiben im vorhandenen stockkompatiblen Profil erhalten.

HIDDEN_NAME-v2 ist auf dem Samsung mit der vorhandenen EZIF-Firmware durch 514 Prüfungen aus echten Test-Apps auf F2FS und FUSE belegt. Das ist ein eigener Runtime-Nachweis für den eingebauten Fehlerfix. Ein EZJ1-Stockpaket und ein erfolgreiches CI-Ergebnis ersetzen keinen Geräte-Boot-Test auf der EZJ1-Firmware. Der Stand der einzelnen Prüfungen steht in [VERIFICATION.md](VERIFICATION.md).

## Quellen und Pakete

- [Öffentliche App-Pakete 1.1.0](https://github.com/kaos2310/Super-Builders/releases/tag/build-center-v1.1.0)
- [EZJ1-Kernel-Lauf](https://github.com/kaos2310/Super-Builders/actions/runs/42894816028)
- [Erfolgreicher HIDDEN_NAME-v2-EZIF-Lauf](https://github.com/kaos2310/Super-Builders/actions/runs/42877994599)

Das Integrations-ZIP enthält die vollständigen `.github/workflows/`-Dateien und `build-center/`. Das separate Manager-Quell-ZIP enthält 1363 Dateien einschließlich der beiden exakten Upstream-Quellstände, Anpassungspatch, Buildanleitung und verifizierten nativen Eingaben. Das SuSFS-Quellarchiv ist ein Quellpaket; das installierbare ReSuSFS-Modul kommt aus dem passenden Kernel-Release.
