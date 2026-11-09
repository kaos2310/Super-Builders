# SukiSU Build Center 1.0

Gewünschtes Ergebnis: dieselbe deutsche Oberfläche als Android-APK, portable Windows-EXE und lokale Web-App. Sie prüft offizielles SukiSU (main oder Release) und SuSFS (ausschließlich gki-android14-6.1), startet die Update-/Build-Pipeline, zeigt konkrete Jobs und liefert den tatsächlich flashbaren Kernel, das passende ReSuSFS-Modul sowie SuSFS-Quellen mit Prüfsummen.

Ausgangspunkt: erfolgreicher Lauf 42129383180 / 4369dc1ae64d3e98e0b83452118ae15f3e5a5a78. Technische Erweiterungsbasis: 41165 / f269b2d31779901efe920c3c8a3f00838e35e119, einschließlich der vorhandenen SuSFS-2.4.0-Portierung. Diese Quellen werden unverändert archiviert; Kandidaten entstehen in flüchtigen CI-Arbeitsverzeichnissen.

Vertrag:

- Offizielle Quellen immer zuerst auf unveränderliche Commit-IDs auflösen. Versionsangaben aus den Quellen lesen.
- SukiSU-Kernel und Userspace aus demselben Commit bauen, Cargo-Lock erhalten.
- SuSFS-Delta dreiseitig gegen den vorhandenen Port zusammenführen. Konflikte und unbekannte ABI-Versionen brechen den Build ab.
- Samsung EZIF, Linux 6.1.162, strenge KMI-/DLKM-/CRC-Prüfungen, KPM und vorhandene Konfiguration beibehalten.
- Keine historischen Kompilierungsnachweise als Nachweise neuer Quellen verwenden. Neue CI-Manifeste benennen ihre tatsächliche Prüfstufe.
- Erfolgreiche vollständige CI erforderlich, bevor ein Kandidat als fertiger Kernel angeboten wird. Artefakt-Hülle von der enthaltenen flashbaren ZIP unterscheiden.
- Keine GitHub-Zugangsdaten in Paketen, URLs oder Quellcode. Web/Windows behalten den Token nur im Arbeitsspeicher; Android verwendet den Android Keystore.
- Android-Installation über den Paketinstaller; Kernel-Download als ZIP. Firmwarewechsel und Flashen sind außerhalb dieser App-Version.

Reihenfolge: (1) gemeinsame API und Oberfläche, (2) parametrisierte CI-Integration und Download-Prüfung, (3) Android- und Windows-Pakete, (4) fokussierte Tests, reale Lesezugriffe und Paketprüfung. GitHub-Veröffentlichung und Aktivierung des Zeitplans separat nach Prüfung des konkreten Pakets.
