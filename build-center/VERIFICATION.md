# Prüfstand 10. November 2026 · EZJ1 / Build Center 1.1.0

## Kernel aus GitHub Actions

[Run 42894816028](https://github.com/kaos2310/Super-Builders/actions/runs/42894816028) ist mit allen sieben Jobs erfolgreich abgeschlossen. Der Kernel-Controller-Commit lautet `bc97d2a44cbd0dfbec23292ceb597925677ec257`.

- Ziel: SM-S928B / S928BXXS6EZJ1 / S928BOXM6EZJ1 / EUX.
- Kernel: Linux 6.1.162, GKI Android 14; Frameworkziel Android 17.
- SukiSU 41168: `674aa00c18adc3d7ef4069c03018d6194230865a`.
- SuSFS v2.4.0: `69b8e734920b8f9ed885ab8d112969719698e242`.
- KernelPatch 0.14.0 / ABI2: `1c5b608916357ac86a94cc736e235db1fac4a29d`.
- Heruntergeladene Kernel-ZIP: `ced6a7c425a6955b953d99de50529448d8adcfa25c1d9341d71f4401171885e1`.
- Tatsächliches 54.857.328 Byte-Image: `41d3b6b8f764b155525de1d3c947fcc1a00f83ad8c8e4fa7fd6b9f55540c1f77`.

Die äußere Actions-Prüfsumme, ZIP-CRC, innere ZIP-Prüfsumme, Linux-Banner, Zeitstempel 13.10.2026 01:54:25 UTC, Firmware-/HIDDEN_NAME-/Runtime-/KPM-Nachweise und eingebettete Konfiguration wurden lokal unabhängig geprüft. Die Firmwareprüfung belegt den Hash des tatsächlich enthaltenen Image. Der Installer verlangt ausdrücklich EZJ1.

Strict-KMI/DLKM-CRC: **2485/2485 exakt**, 0 fehlend, 0 Varianten, 0 Referenz-Fallbacks. `Module.symvers` hat SHA256 `13da04bcfc0754b1ac4a1dcc869e572e67d878fc399b1b7d61640d08fb83ee6b`. MODVERSIONS und die strenge Ablehnung bleiben aktiv. CPU-/PID-Limitoptionen bleiben aus.

Die sechs Originalarchive wurden vollständig per SHA256 und Odin-Tar-MD5 geprüft. Die Stock-Konfiguration stimmt bytegenau mit der geprüften Basiskonfiguration überein.882 Moduldateien / 543 eindeutige Module lieferten 5470 eindeutige Import-CRCs; sämtliche strengen Baselineeinträge stimmen überein. Der genaue separate Samsung-EZJ1-OSS-Abgleich ist nicht belegt; der bestehende Samsung-Port auf AOSP6.1.162 bleibt Grundlage.

## HIDDEN_NAME-v2

Der neue EZJ1-Lauf besteht 4202 C-Prüfungen über fünf native/Compat-Verzeichnis-ABIs, jeweils mit und ohne ZeroMount. Die Tests reproduzieren die alte Namenslücke und den v1-Fehler bei teilweise gefüllten Puffern; der korrigierte Code besteht die Positiv- und Negativkontrollen.

Der vorhandene Kernel aus dem [erfolgreichen EZIF-v2-Lauf](https://github.com/kaos2310/Super-Builders/actions/runs/42877994599) wurde auf dem Samsung bereits gebootet und mit zwei echten unprivilegierten Test-Apps geprüft: **514 Prüfungen**, je 257 auf internem F2FS und externem FUSE. Java-Verzeichnislisten, libc readdir, direkte getdents64-Aufrufe mit kleinen/großen Puffern, bestehende FDs, Owner-/Root-Ausnahmen und OFF-ON-OFF-ON bestanden. Die Test-Apps und temporären Geräte-Testdateien wurden entfernt.

**EZJ1 wurde nicht auf dem Telefon gebootet.** Das Telefon verwendet weiterhin EZIF; ein CI-Nachweis ersetzt diesen fehlenden Firmware-/Geräte-Test nicht.

## Build Center 1.1.0

| Prüfung | Ergebnis |
| --- | --- |
| Python-Controller-/Server-/Firmware-/Downloadtests | 33 bestanden |
| JavaScript-API-/Auswahl-/Auftragstests | 11 bestanden |
| Edge-Browser-Funktionstests | 10 bestanden; keine JavaScript-Fehler |
| Mobile Webansicht | 390 px ohne horizontalen Überlauf |
| Android-APK |Java/DEX/Ressourcen/Signatur bestanden; Update auf Samsung installiert und aktuelle Quellen/EZJ1-Profil visuell geprüft |
| Android-Updatezertifikat |Bestehende Build-Center-Identität unverändert |
| Windows-EXE |Echte portable EXE gestartet; Version 1.1.0, lokaler Server und Schutzprüfung bestanden |
| Echte Kernelbereitstellung über EXE |Öffentlichen EZJ1-Kernel geladen, SHA256 und Firmware-Nachweis kontrolliert, identische ZIP ausgeliefert |
| Falsche Firmware/anderes Image |Durch Downloadtests abgelehnt |

## Zusätzlicher Root-Manager

Paket `com.kaoslab.sukisu.manager`, Code 41168, ARM64, Android-Ziel37, `debuggable=false`. APK-SHA256: `8de3ff7599eca328d500d35cede9ffe373d9416f6451f1a8c8d1411e24b73166`. Öffentliches Zertifikat: 744 Bytes / `28ef122baa66fe3fa7d49ce2ca4d652b16c22cd51d719d8e606a0ad0b8ee2d36`. Die offizielle Manager-APK blieb installiert. Die zusätzliche Registrierung wurde nach ausdrücklicher Zustimmung über die native SukiSU-Manager-Verwaltung angelegt; die vorherige Vertrauensliste ist lokal gesichert.

ksud/UAPI6, kptools und kpimg im APK stimmen bytegenau mit den protokollierten gepinnten Eingaben überein. Die eigene Aktualisierung prüft nur die passende Paketfamilie aus Super-Builders; Installation kontrolliert Version und Zertifikat.

Die vollständige Release-JVM-Testsuite besteht unter der vorhandenen Linux-Java-Laufzeit mit **242 Tests**. Die sechs neuen Runtime-Tests prüfen Protokoll, ABI-Größe, Masken, unsigned Generationen, genau einen Setter, veraltete Aufträge und unerwartete Fremdbit-Änderungen. Beim vollständigen Windows-Lauf waren zusätzlich fünf Unix-Dateisystemtests nicht kompatibel; der Linux-Vergleich bestätigt die komplette Suite. Ein dabei belegter Fehler beim Fallback von abgewiesenen Upload-Zielen wurde korrigiert. Die Upload-Überwachung hat ein 25-Sekunden-Minimum; der zugehörige Test wartet jetzt ausreichend lange und prüft weiterhin den tatsächlichen Wechsel vor der 35-Sekunden-Antwort.

Die vier neuen Schalter wurden **in der installierten Release-App** aus- und wieder eingeschaltet und nach jedem Touch unabhängig am Kernel geprüft:

| Kontrolle | Beobachtete Kernelmaske | Generation |
| --- | --- | --- |
| UID-Filter |15→14→15 |9→10→11 |
| HIDDEN_NAME |15→13→15 |11→12→13 |
| Unicode |15→11→15 |13→14→15 |
| Symbol-Hiding |15→7→15 |15→16→17 |

Ausgangsmaske 15 wurde wiederhergestellt. Dieser App-Runtime-Test lief auf dem vorhandenen EZIF-Kernel 41168/UAPI6; seine Beobachtung wird nicht als EZJ1-Boot-Test ausgegeben.

[Öffentlicher EZJ1-Kernel-Download](https://github.com/kaos2310/Super-Builders/releases/tag/s928b-ezj1-suki41168-susfs2.4.0-674aa00c-69b8e734-hidden-name-readdir-v2-r42894816028). App-/Quellpakete und Prüfsummen stehen im separaten Build-Center-v1.1.0-Release. Lokale Geräte-Backups, private Schlüssel, Token und UI-Screenshots werden nicht in öffentliche Pakete aufgenommen.
