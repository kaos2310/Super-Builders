# Prüfstand 9. November 2026

## App-Pakete

| Prüfung | Ergebnis |
| --- | --- |
| Java-Kompilierung, DEX, Android-Ressourcen, ZIP-Ausrichtung | Bestanden |
| APK-Signatur | APK Signature Scheme v3 gültig; ein Signierer |
| Zertifikat SHA-256 | `9c6a2c166e17ec4bafa536ff1b22766c6a0f4743652042bf7b1ff93f096de419` |
| Tatsächliche APK-Installation und Start im Android-17-Emulator | Bestanden |
| Tatsächliche APK-Installation und Kaltstart auf Samsung SM-S928B | Bestanden; Startmeldung `Status: ok`, 346 ms |
| Systemleisten im Emulator und auf Samsung | Native Container-Insetkorrektur visuell geprüft |
| Samsung-App-Fehlerlogs nach Start | Keine Einträge für eigene AndroidRuntime-/Asset-/Chromium-Fehler |
| Windows-EXE | Mit Python-Laufzeit gebaut; tatsächlicher Start und ausgelieferte Oberfläche über lokalen Server geprüft |
| Web-Oberfläche | Zehn Browser-Szenarien auf Desktop und bei 390 Pixel Breite bestanden; keine JavaScript-Fehler, kein horizontaler Überlauf |
| Python-Verhaltenstests | 26 bestanden |
| JavaScript-API-Verhaltenstests | 9 bestanden |
| GitHub-Workflow-Prüfung | Sechs Workflows mit actionlint v1.7.12 geprüft, keine Befunde; ShellCheck/Pyflakes in diesem Lauf deaktiviert |
| ReSuSFS für den neuen Quell-Pin | 24 echte Shell-Grenztests unter WSL und 42 UI-Grenzprüfungen bestanden; ARM64-Neubau bleibt Teil des noch ausstehenden GitHub-Laufs |

Ein Windows-aapt2-Paketierungsfehler mit Rückwärtsschrägstrichen in Assetnamen wurde anhand des echten Emulatorfehlers korrigiert. Der Build normalisiert jetzt sämtliche APK-ZIP-Pfade vor Ausrichtung und Signierung; ein Regressionstest deckt diesen Fehler ab.

## Per ADB auf dem Samsung beobachtet

- Modell SM-S928B, Firmware S928BXXU6EZIF, CSC EUX, Android 17 / SDK 37.
- Aktiver Kernel meldet Linux 6.1.162 / android14 / EZIF; SELinux Enforcing.
- Installierter Manager: SukiSU 41165, v4.3.0-r2.
- Aktueller Daemon: `ksud 4.3.0-r2-15-gd7d04281 (uapi: 6)`.
- Der private ReSuSFS-CLI liest vom Kernel SuSFS v2.4.0 und 14 aktive Funktionen, einschließlich Priority UID Filter, Hidden Name und Unicode Filter.
- ReSuSFS-Modul r2 / `versionCode=2026110901` ist vorhanden. Es verwendet einen privaten CLI; ein globales `/data/adb/ksu/bin/ksu_susfs` ist hier nicht vorhanden und wird durch die neue App nicht angelegt.
- Die neue App `com.kaoslab.buildcenter`, Version 1.0.0, wurde für den angeforderten ADB-Test installiert und gestartet. Die echte Oberfläche liest SukiSU 41168 und SuSFS 2.4.0 / Commit `69b8e734920b`.
- Anschließend wurde App 1.0.1 mit demselben Signierschlüssel per ADB aktualisiert (`versionCode=2`), gestartet und ohne eigene Fehlerlogs geprüft. Ein Browser-Regressionslauf reproduzierte zuvor zwölf statt einer Jobabfrage ohne Token; die korrigierte Version hält die Abfragepause ein und übernimmt nach abgeschlossenen Läufen den nächsten stündlichen Lauf.
- Der tatsächliche App-Download nach `Download/KAOSLAB/SuSFS-v2.4.0-69b8e734-sources.zip` wurde per ADB zurückgelesen. 128786 Bytes, ZIP-CRC und Versionsheader stimmen.
- SHA-256 dieses Downloads: `0b27808718615ad94b6cdacbcd15d8a27b22f3126fee3dd644ab4e72d2fa16bc`.
- Es wurde kein Kernel geflasht und kein neuer Manager oder ReSuSFS auf dem Telefon installiert. Der Telefon-Test umfasst die neue Build-Center-App und den Quellarchiv-Download.

## Echte Quellen und Kernel-Download

Der offizielle SukiSU-Commit `674aa00c18adc3d7ef4069c03018d6194230865a` hat 3983 Commits. Die überprüfte offizielle Formel ergibt **41168**. Der stabile Release ist v4.3.0-r2; für 41168 war bei der Prüfung keine passende APK im neuesten stabilen Release vorhanden.

SuSFS `gki-android14-6.1` steht auf `69b8e734920b8f9ed885ab8d112969719698e242`, weiterhin **v2.4.0**. Der Vergleich gegen `a2165b6f875b73e2f87d3c6f12814efac8de061d` änderte nur `kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch`. Es gab keine geänderten effektiven SukiSU/GKI-Dateien. Die 30 offiziellen CLI-Quelldateien wurden aus dem neuen Pin geladen; ihre Inhalte stimmen mit der vorhandenen geprüften CLI-Quelle überein.

Eine frische Kopie der vorhandenen 41165-Builder-Dateien wurde für 41168 migriert. Die historischen Kompilierungsnachweise wurden dabei ausdrücklich nicht als Nachweise des neuen Quellpaars übernommen.

Zusätzlich wurde ein bereits vorhandenes echtes Kernel-Artefakt vollständig geprüft: äußere SHA-256 `e2c19e21476883513175df698dbaac68818b3514e4b68f6a5f924683c9c5cb11`, daraus die tatsächliche 19691932 Byte große AnyKernel3-ZIP mit SHA-256 `94e25345a527af5e03173be78ebb751f9a44180f84b2c518dac3850e4084b548` entnommen. Dies ist ein Referenz-41165-Paket, kein neu gebauter 41168-Kernel.

## Veröffentlichung und vollständiger Kernel-Lauf

Die GitHub-Integration ist auf `main` veröffentlicht und der stündliche Workflow aktiv. Der erste vollständige Lauf [42712496915](https://github.com/kaos2310/Super-Builders/actions/runs/42712496915) am Controller-Commit `f4c5d176d15ddd82eca66591b3e0925d4d694d5c` wurde mit allen sieben Jobs erfolgreich abgeschlossen. Er dauerte von 22:30:33 UTC bis 22:54:45 UTC, insgesamt 24 Minuten und 12 Sekunden. Kernel, ARM64-Userspace, ReSuSFS und ZeroMount-Kompatibilität wurden in diesem Lauf gebaut; strenge Samsung-KMI-/DLKM-/CRC-, Konfigurations- und Paketprüfungen bestanden.

Die erzeugte Kernel-ZIP ist 19686348 Byte groß und hat SHA-256 `63851bda2c88da6ce1ed2fc5c3929b071d7827fff903723a0670e1959422375d`. Der öffentliche Download ohne Anmeldung wurde mit dem Actions-Artefakt abgeglichen; ZIP-CRC, Quellmanifest, ARM64-Image und eingebettete Konfiguration wurden zusätzlich lokal geprüft. CPU-/PID-Limitoptionen bleiben ausgeschaltet. Das ReSuSFS-Modul hat SHA-256 `db756e9784c201dc53dbf1591c569a632e5908978d0837db8d4640e9e7a4f6e1`; alle enthaltenen Mitglied-Prüfsummen und die beiden echten ARM64-Binärdateien sind geprüft.

Die Ergebnisse stehen im [Kernel-Release](https://github.com/kaos2310/Super-Builders/releases/tag/s928b-ezif-suki41168-susfs2.4.0-674aa00c-69b8e734). App-Downloads sind als Release veröffentlicht. Eine physische Bootprüfung des neu erzeugten Kernels wurde nicht durchgeführt; es wurde weiterhin kein Kernel auf dem Telefon geflasht.

Die vorhandenen 41150- und 41165-Arbeitsverzeichnisse blieben unverändert. Lokale Prüfberichte und Screenshots liegen unter `.test-results/` und werden nicht in öffentliche Quellpakete aufgenommen.
