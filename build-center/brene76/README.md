# BRENE 0.0.76 in ZeroMount Guard6.13

Die Integration baut auf dem vollständigen bisherigen Guard6.13-Modul auf. Sie
ersetzt keine Boot- oder Ownership-Hooks durch die eigenständigen BRENE-Skripte.
Das Originalarchiv ist über SHA256 gebunden und wird ausschließlich als inerte
Provenienz mitgeliefert. `DELTA-75-76.json` hält den Vergleich der beiden echten
Originalarchive fest. Löschskripte, automatische globale Werkzeug-Ersetzungen
und die eigenständige BRENE-WebUI werden nicht in den Guard-Bootpfad übernommen.

Alle sieben vorhandenen Adapter-Optionen verwenden weiterhin
`/data/adb/zeromount/brene71/options`. Die alten Befehle `brene71` und `brene75`
und die alte BRENE-Seite bleiben erreichbar. Unbekannte zukünftige Schlüssel
und Kommentare bleiben beim Speichern als Daten erhalten. Die bestehenden
Regel-, Properties-, Settings-, Patchdatum-, Mount- und VFS-Funktionen bleiben
im vollständigen Modul enthalten.

BRENE76 ergänzt fünf standardmäßig ausgeschaltete Optionen:

* Eigene SUS_PATH-Ausnahmen: eine Liste von Paketnamen, deren App-UIDs die
  registrierten Pfade sehen dürfen. Die leere Liste sendet den dokumentierten
  Komma-Sentinel und entfernt die Ausnahmen. Diese Liste ist unabhängig von der
  Priority-UID-Liste und den vier vorhandenen Runtime-Schaltern.
* Priority-UID-Filter für alle App-UIDs ab 10000 aus Androids `packages.list`.
  Wenn auch die bisherige Drittanbieter-Option eingeschaltet ist, hat die breitere
  Liste Vorrang; der gespeicherte Wert der bisherigen Option bleibt erhalten.
* SUS_MAP für vorhandene Vector-Dateien, ohne die Moduldateien zu verändern.
* Eine vorhandene OEM-Unlock-Property auf 0 setzen.
* Optionale Bereinigung von Build-Fingerprint-Markern gemäß BRENE76.

Speichern verändert nur die Konfiguration. Anwendung erfolgt beim nächsten Boot
nach dessen Abschluss unter den bestehenden SUSFS-/BRENE-Freigaben und ohne
externen SUSFS-Verwalter. Die beiden Property-Optionen beachten zusätzlich die
bestehende Properties-Gruppenfreigabe. Der bisherige Logcat- und logd-Schalter
bleibt vollständig erhalten, obwohl BRENE76 den zusätzlichen logd-Writer entfernt.

Der neue SUS_PATH-Befehl hat keinen Listen-Getter. Die Oberfläche behauptet daher
keine bestätigte Kernel-Anwendung aufgrund einer gespeicherten Liste oder einer
Versionsnummer. Der Adapter verwendet dafür das private, im gleichen Build neu
kompilierte `bin/ksu_susfs` und wertet dessen Rückgabecode aus. Kein globales
Werkzeug wird ersetzt. Das Paket verlangt den zugehörigen
`SUSFS-TOOL-BUILD.json`-Beleg mit exakt passendem SUSFS-Pin, Binärhash, Ziel und
Quellhashliste.

Die vorhandene Runtime-Sektion bleibt ein separater Zusatz: aktueller Boot,
unveränderte ABI-v1-Prüfung, Ownership-Freigaben, Generation/CAS und unabhängiges
Rücklesen. Öffnen und Aktualisieren der Oberfläche bleiben lesend.

Prüfungen:

```text
node build-center/brene76/test.mjs
python3 -B build-center/brene76/test.py
python3 -B build-center/brene76/test_overlay.py --helpers PREPARED_HELPERS
python3 -B build-center/guard6/test.py --helpers PREPARED_HELPERS --plan PLAN_JSON --runtime-helper AARCH64_RUNTIME --susfs-tool AARCH64_SUSFS_TOOL
```

Die Shell- und Installationstests benötigen Linux/WSL. Die Overlaytests verwenden
explizit synthetische Belege und erzeugen kein Release-Artefakt. Der vollständige
Pakettest benötigt die echten neu gebauten Helfer. Ein erfolgreicher CI-Build
belegt keinen Geräte-Boot oder erfolgreichen Geräteeinsatz.
