# Integrierte ZeroMount-Menüs für SukiSU 41165

`apply.py MODULE_DIR --receipt UI-VERIFICATION.json` ergänzt die geprüfte
Guard6.13-WebUI. Anschließend müssen die Paket-Checksummen und der Build-Manifest
vom aufrufenden Packager neu erzeugt werden. Der Helfer verändert keine
Backend-Skripte, Kernel-Binärdateien, gespeicherten Regeln oder Gerätekonfiguration.

Der Einstieg befindet sich direkt in ZeroMount → Settings → SUSFS & BRENE.
Die Übersicht zeigt die tatsächlich gelesenen Freigaben und den externen
Verwalterstatus. Eigene Regeln, BRENE-Funktionen und Patchdatum/Properties
verwenden dieselbe responsive Oberfläche und Navigation. Rückwege öffnen
über `index.html#settings` unmittelbar den nativen Settings-Tab.

Entfernt werden der die untere Navigation überlagernde schwebende Link, die
veraltete ReSukiSU-35187-Beschriftung, doppelte versionsbezogene BRENE-Menüs
und die statische Aussage, UID-Gating sei ausschließlich eine Buildoption.
`brene71.html` bleibt als Kompatibilitätsweiterleitung auf BRENE verfügbar.
Die vorhandenen Funktionen einschließlich `kernel_umount`, `sync_su_compat`
und `try_umount` bleiben erhalten; sie sind laut aktueller Geräteabfrage
weiterhin unterstützt. Keine gespeicherten Optionen werden gelöscht.

Die Übersicht akzeptiert die vom Kernel gemeldete SUSFS-Version, einschließlich
v2.4.0. Die nativen ABI-/Versionsprüfungen bleiben für eigentliche SUSFS-Regeln
zuständig und müssen vom Packager zusammen mit dem nativen Core auf 2.4
aktualisiert werden. Die WebUI ersetzt diese Prüfungen nicht.

Runtime v1 benötigt den aus `susfs-runtime-v1/susfs-runtime.c` kompilierten
Helfer unter `bin/susfs-runtime`. Die vier Laufzeit-Schalter sind nur nach
bestätigtem ABI, gültiger Featuremaske, gelesener Generation und aktiven SUSFS-
und BRENE-Freigaben editierbar. Unmittelbar vor dem Aufruf werden beide
Owner-Freigaben erneut geprüft. Ein Fehler oder unbestätigter Readback sperrt
weitere Schreibzugriffe bis zum Aktualisieren. Öffnen liest nur Status.
Die Laufzeitwerte gelten für den aktuellen Boot; Regeln bleiben gespeichert.

Prüfung:

```powershell
node test.mjs
python test.py PFAD_ZUM_GUARD613_MODUL
```

`test.mjs` prüft read-only Start, Feature-/Owner-Gates, manipulierte Argumente,
CAS/Readback, Abbruch, Fehler, Bridge und Theme-Auswahl. `test.py` spielt das
Overlay auf einem Modul-Snapshot ab, prüft den Erhalt sämtlicher übriger
Dateien und Einstellungen, die native Navigation sowie Idempotenz und das
Abweisen unbekannter nativer WebUI-Layouts. Ein Geräte-WebView-Test ist
hiermit nicht behauptet.
