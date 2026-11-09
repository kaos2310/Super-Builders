# SukiSU Build Center 1.0.1

Deutsche App für Android, Windows und den lokalen Browser. Gemeinsame Oberfläche, keine laufenden Fremdserver erforderlich. Der Kernel-Build läuft in deinem GitHub-Repository.

## Starten

| Variante | Datei | Start |
| --- | --- | --- |
| Android ab Android 10 | `SukiSU-Build-Center-1.0.1.apk` | APK auf dem Telefon installieren und öffnen |
| Windows 11, x64 | `SukiSU-Build-Center-1.0.1.exe` | Portable EXE öffnen; sie nutzt Microsoft Edge als App-Fenster |
| Lokale Web-App | `SukiSU-Build-Center-Web-1.0.1.zip` | Entpacken und `Start-Web.cmd` öffnen; Python ist unter Windows im Paket enthalten |
| Web auf Linux/macOS | Quellpaket | Python 3.11 oder neuer: `python3 desktop.py --web` |

Die Windows-Anwendung und die lokale Web-App binden ausschließlich `127.0.0.1`. Nach dem Schließen der Oberfläche endet der Server nach ungefähr drei Minuten. `--stay` hält ihn ausdrücklich geöffnet. Die Web-Oberfläche kann zusätzlich als PWA installiert werden. Hintergrund-Builds werden vom GitHub-Zeitplan übernommen.

## GitHub-Verbindung

Voreingestellt sind `kaos2310/Super-Builders`, Branch `main` und der neueste offizielle SukiSU-Entwicklungsstand. Alternativ lässt sich die neueste veröffentlichte Version auswählen.

Für den Build-Start einen Fine-grained Personal Access Token für genau dieses Repository eintragen:

- **Actions: Read and write** für Workflow-Start, Status und Artefakte.
- **Contents: Read** für Quellen und Releases.

Der Token bleibt in Web und Windows nur im Arbeitsspeicher. Android kann ihn auf ausdrücklichen Wunsch über den Android Keystore verschlüsselt speichern. Öffentliche Quellprüfungen und öffentliche Release-Downloads funktionieren ohne Token, vorbehaltlich der API-Limits von GitHub und GitLab. Ohne Token fragt die App laufende Builds höchstens alle fünf Minuten ab; mit Token ist die Statusabfrage häufiger.

## Was die App erledigt

1. SukiSU `main` oder den offiziellen Release-Tag in eine konkrete Commit-ID auflösen; die Versionsnummer aus der vollständigen Commitanzahl und der überprüften offiziellen Kbuild-Formel bestimmen.
2. SuSFS ausschließlich im passenden Zweig `gki-android14-6.1` prüfen. Commit und Versionsmakro werden separat gelesen: ein neuer Commit kann dieselbe Versionsnummer behalten.
3. Einen Build-Auftrag mit eindeutiger ID an `build-center.yml` senden und ausschließlich den zugehörigen Actions-Lauf verfolgen.
4. Die Pipeline lädt Werkzeuge und Quellen, integriert die Updates und baut Kernel, ARM64-Userspace, ZeroMount-Kompatibilität und das passende ReSuSFS-Modul.
5. Erst nach erfolgreichen Kernel-, KMI-, DLKM-/CRC- und Paketprüfungen ein GitHub-Prerelease mit der echten AnyKernel3-ZIP, ReSuSFS-ZIP, SuSFS-Quellarchiv, Build-Plan und SHA256SUMS erzeugen. Eine offizielle Manager-Release-APK wird beigefügt, wenn ihre Versionsnummer zum gewählten SukiSU-Stand passt.
6. Alle 15 Minuten bei geöffneter App auf Quellen prüfen. Nach Installation der GitHub-Integration prüft Actions stündlich selbstständig, auch wenn sämtliche Apps geschlossen sind. GitHub kann geplante Läufe verzögert starten; der Zeitplan liegt bei Minute 17 jeder Stunde.

Eine neue Manager-Version kann auf `main` bereits existieren, bevor eine passende signierte APK als Release vorliegt. Die App bietet dann den offiziellen Actions-Link an und kennzeichnet diesen Zustand. Auf Android prüft der APK-Download Paketname und offizielles Signierzertifikat, bevor der Android-Paketinstaller geöffnet wird.

Bei Actions-Artefakten wird die SHA-256-Prüfsumme der äußeren GitHub-ZIP geprüft und daraus genau eine tatsächliche Kernel-ZIP entnommen. `anykernel.sh`, Kernel-Image und Strict-KMI-Nachweis müssen darin enthalten sein. Bei Downloads ohne veröffentlichte Vergleichssumme wird die berechnete SHA-256 angezeigt. ReSuSFS- und Kernel-ZIPs werden als Dateien bereitgestellt; die App flasht keinen Kernel und startet kein Telefon neu.

## Einmalige GitHub-Integration

Die Integration und der App-Quellcode sind auf `main` veröffentlicht. Der stündliche Workflow ist aktiv. Der [erste vollständige Lauf](https://github.com/kaos2310/Super-Builders/actions/runs/42712496915) ist mit allen sieben Jobs erfolgreich abgeschlossen. Die [Kernel- und ReSuSFS-Downloads](https://github.com/kaos2310/Super-Builders/releases/tag/s928b-ezif-suki41168-susfs2.4.0-674aa00c-69b8e734) sowie die [App-Pakete](https://github.com/kaos2310/Super-Builders/releases/tag/build-center-v1.0.1) sind öffentlich verfügbar.

Das Paket `SukiSU-Build-Center-GitHub-Integration-1.0.1.zip` enthält bereits die vollständige, direkt ins Repository kopierbare Struktur:

```text
.github/workflows/build-center.yml
.github/workflows/build-center-cache.yml
.github/workflows/build-center-userspace.yml
.github/workflows/build-center-zeromount.yml
.github/workflows/build-center-resusfs.yml
.github/workflows/build-center-strict.yml
build-center/config.json
build-center/center_core.py
build-center/ci/...
```

Nach Veröffentlichung auf `main` sind manueller Start aus der App und stündlicher Zeitplan aktiv. Das Workflow-Token erhält im jeweiligen Job die erforderlichen Rechte; für den Zeitplan ist kein persönlicher Token als Repository-Secret nötig. Bereits veröffentlichte identische Quellpaare werden übersprungen. Nach einem fehlgeschlagenen Bau wartet dieselbe Quellkombination 24 Stunden auf einen automatischen Wiederholungsversuch; die Option für einen ausdrücklichen Neubau hebt diese Wartezeit auf. Ein ausdrücklich angeforderter Neubau bekommt einen eigenen unveränderlichen Release-Tag.

Für dauerhafte Änderungen am Zeitplan/Kanal `build-center/config.json` und den Hauptworkflow anpassen. Zum Pausieren kann der Hauptworkflow in GitHub Actions deaktiviert werden; die App zeigt den deaktivierten Zustand an.

## Kernel-Profil und Grenzen automatischer Updates

Referenz ist der erfolgreiche Lauf `42129383180`. Die technische Grundlage ist die vorhandene 41165-Linie am unveränderlichen Commit `f269b2d31779901efe920c3c8a3f00838e35e119`. Die vorhandenen Branches und Dateien werden nicht verändert; jeder CI-Job lädt eine frische Kopie.

Das Profil bleibt SM-S928B/EUX, Firmware S928BXXU6EZIF, Android-14-GKI, Linux 6.1.162, KPM, DroidSpaces und strenge Samsung-KMI-/DLKM-/CRC-Prüfungen. CPU-/PID-Limitoptionen bleiben ausgeschaltet. Andere Firmware oder Kernel-Hauptversionen werden nicht automatisch gewählt.

Neue Quellstände erhalten keine übernommenen historischen Kompilierungsnachweise. Die Pipeline erfasst ihre tatsächlichen Quellen neu und führt die semantischen Tests und den vollständigen Build aus. SuSFS-Änderungen werden dreiseitig mit dem vorhandenen Port zusammengeführt; Konflikte, geänderte UAPI oder nicht unterstützte Module brechen den Build ab. Die ReSuSFS-Integration unterstützt derzeit die geprüfte SuSFS-2.4.0-Schnittstelle. Ein künftiger inkompatibler Versionssprung braucht eine Anpassung; er wird nicht als fertiger Download veröffentlicht.

## Lokal nachbauen und prüfen

Android benötigt JDK 17 oder neuer und Android SDK Plattform 36 / Build Tools 36.0.0. `tools/Build-Android.ps1` verwendet standardmäßig die auf diesem PC vorhandenen Pfade. Der lokale App-Signierschlüssel liegt unter `private/` und ist in keinem Auslieferungs- oder GitHub-Paket enthalten.

Für Windows: PyInstaller 6.20.0 unter `.build-deps` installieren und `tools/Build-Windows.ps1` ausführen. Die Windows-EXE enthält die Python-Laufzeit. Pillow wird ausschließlich zum Erzeugen der Symbole verwendet, PyYAML ausschließlich zur Workflow-Erzeugung.

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
npm ci --ignore-scripts
npm test
node tests/browser.mjs
```

Die Browser-Tests verwenden kontrollierte API-Antworten und starten keinen echten GitHub-Build. `tools/live_smoke.py` prüft echte offizielle API-Antworten, die Quellmigration und einen bereits vorhandenen Kernel-Download in einem frischen isolierten Testordner. Die Prüfergebnisse stehen in `VERIFICATION.md`.
