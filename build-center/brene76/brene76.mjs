// Additive UI: the existing Guard6.10 application assets are never rewritten.
export const KEYS = Object.freeze(['shrink_buffer_size','spoof_hosts','spoof_libstagefright','hide_lineage_strings','disable_child_process_restrictions','hide_ksu_directories','hide_third_party_apps','hide_all_apps_with_uid_10000_and_above','sus_path_uid_filter','hide_vector_injection','hide_oem_unlocking_toggle','sanitize_build_fingerprint']);
const BIN = '/data/adb/modules/meta-zeromount/bin/zm';
export const STATUS_COMMAND = `${BIN} brene76 status`;
const LABELS = [
 ['Logpuffer auf 64 KiB','logcat und persist.logd.size; Anwendung erst nach Boot-Abschluss.'],
 ['Stock-Hosts über OPEN_REDIRECT','App-Sicht für umounted UIDs ab 10000; ersetzt eine vorhandene Hosts-Filterung in dieser Sicht.'],
 ['libstagefright ausblenden','Optionale leere Dateisicht; kann Multimedia-Apps beeinträchtigen.'],
 ['LineageOS-Strings ausblenden','Optionale leere Sicht auf Policy-/Konfigurationsdateien für umounted Apps.'],
 ['Phantom-Prozessbeschränkung lockern','Android-Property; CPU- und PID-Kernel-Limits bleiben aus.'],
 ['KernelSU-Verzeichnisse verbergen','SuSFS-Dateisicht für die BRENE76-Paketliste; keine Ordnerlöschung.'],
 ['Drittanbieter-UIDs filtern','Ersetzt beim nächsten Boot die Priority-UID-Liste durch alle Drittanbieter-Apps. Nicht gleichzeitig mit einer eigenen Manager-Liste verwenden.'],
 ['Alle App-UIDs ab 10000 filtern','Priority-UID-Liste aus packages.list, einschließlich entsprechender System-Apps. Hat bei gemeinsamer Auswahl Vorrang vor der Drittanbieter-Liste; deren gespeicherter Wert bleibt erhalten.'],
 ['Eigene SUS_PATH-Ausnahmen anwenden','Die unten aufgeführten Apps dürfen registrierte SUS_PATH-Pfade sehen; alle anderen App-UIDs behalten die bisherige verborgene Sicht. Anwendung beim nächsten Boot.'],
 ['Vector-Dateisichten verbergen','SUS_MAP für vorhandene arm64-/arm32-Dateien von zygisk_vector; keine Moduldatei wird verändert.'],
 ['OEM-Unlock-Menüeintrag ausblenden','Setzt eine vorhandene ro.oem_unlock_supported-Property auf 0. Benötigt die bestehende Properties-Freigabe; ändert den Bootloader-Zustand nicht.'],
 ['Build-Fingerprint bereinigen','Optionale BRENE76-Textbereinigung für userdebug/test-keys und bekannte ROM-Marker. Benötigt die Properties-Freigabe und ändert keine Hardware-Attestierung.'],
];
export function filterSaveCommand(value) {
  if (typeof value !== 'string' || value.length > 65534 || !/^[A-Za-z0-9_., \t]*$/.test(value)) throw new Error('Ungültige Paketliste');
  const names = [...new Set(value.split(',').map(name => name.trim()).filter(Boolean))];
  if (names.some(name => name.length > 255 || name === '.' || name === '..' || !/^[A-Za-z0-9_.]+$/.test(name))) throw new Error('Ungültiger Paketname');
  return `${BIN} brene76 filter-set '${names.join(',') || ','}'`;
}
export function saveCommand(key, value) {
  if (!KEYS.includes(key) || typeof value !== 'boolean') throw new Error('Ungültige Einstellung');
  return `${BIN} brene76 set ${key} ${value ? 'true' : 'false'}`;
}
export function formatReport(report) {
 if (report.version !== '0.0.76') throw new Error('Unerwartete Adapterversion');
 return {kernel:'BRENE 0.0.76 · Guard6.13-Adapter\nGerätetest noch nicht durchgeführt.',peers:'UIDGate2, BootGuard2 und bestehende Writer-Adapter bleiben erhalten. Keine zweite BRENE-Installation erforderlich.',mounts:'Neue Umleitungen sind optional und prüfen SUSFS v2.4.0 sowie OPEN_REDIRECT. Bereits registrierte Regeln bleiben bis zum Neustart aktiv.'};
}
// KernelSU WebView's documented callback-shaped bridge, as shipped in the input.
let callbackId = 0;
export function execReadOrSave(command, scope = globalThis) {
  return new Promise((resolve, reject) => {
    if (typeof scope.ksu?.exec !== 'function') { reject(new Error('Root-Manager-WebView erforderlich')); return; }
    const name = `zm_brene76_${Date.now()}_${callbackId++}`;
    const cleanup = () => { clearTimeout(timer); delete scope[name]; };
    const timer = setTimeout(() => { cleanup(); reject(new Error('Abfrage-Zeitlimit; Status erneut lesen')); }, 15000);
    scope[name] = (errno, stdout, stderr) => {
      cleanup();
      if (Number(errno) !== 0) reject(new Error(String(stderr || `Exit ${errno}`)));
      else resolve(String(stdout));
    };
    try { scope.ksu.exec(command, '{}', name); } catch (error) { cleanup(); reject(error); }
  });
}

export function start(doc, scope = globalThis, exec = execReadOrSave) {
  const byId = id => doc.getElementById(id);
  const inputs = new Map();
  const message = text => { byId('message').textContent = text; };
  let pending = false;
  let savedFilter = ',';
  function disableAll(value) {
    byId('refresh').disabled = value;
    byId('filter-save').disabled = value;
    byId('filter-packages').disabled = value;
    for (const input of inputs.values()) input.disabled = value;
  }
  function applySettings(report) {
    const settings = report.settings;
    if (settings?.error || !settings?.values) throw new Error(settings?.error || 'Konfiguration nicht lesbar');
    // Validate the entire response before enabling any mutation controls.
    for (const key of KEYS) if (!['true', 'false'].includes(settings.values[key])) throw new Error(`Ungültiger Wert: ${key}`);
    filterSaveCommand(report.sus_path_uid_filter_packages);
    savedFilter = report.sus_path_uid_filter_packages;
    byId('filter-packages').value = savedFilter === ',' ? '' : savedFilter;
    for (const key of KEYS) inputs.get(key).checked = settings.values[key] === 'true';
  }
  async function refresh() {
    if (pending) return;
    pending = true; disableAll(true); message('Lese Status …');
    try {
      const report = JSON.parse(await exec(STATUS_COMMAND, scope));
      const display = formatReport(report);
      for (const key of ['kernel', 'peers', 'mounts']) byId(key).textContent = display[key];
      applySettings(report); disableAll(false); message('Status gelesen. Keine Geräteeinstellungen verändert.');
    } catch (e) { message(`Fehler: ${e.message}`); byId('refresh').disabled = false; }
    finally { pending = false; }
  }
  for (const [i, key] of KEYS.entries()) {
    const label = doc.createElement('label');
    const input = doc.createElement('input'); input.type = 'checkbox'; input.disabled = true; input.id = key;
    const text = doc.createElement('span'); text.textContent = LABELS[i][0];
    const description = doc.createElement('small'); description.textContent = LABELS[i][1]; text.append(description);
    label.append(input, text); byId('settings').append(label); inputs.set(key, input);
    input.addEventListener('change', async () => {
      if (pending) return;
      const desired = input.checked;
      if (!scope.confirm(`${LABELS[i][0]} ${desired ? 'aktivieren' : 'deaktivieren'}? Nur Konfiguration speichern; Anwendung ab nächstem Boot.`)) { input.checked = !desired; return; }
      pending = true; disableAll(true);
      try {
        await exec(saveCommand(key, desired), scope);
        const report = JSON.parse(await exec(STATUS_COMMAND, scope));
        applySettings(report);
        if (inputs.get(key).checked !== desired) throw new Error('Gespeicherter Wert stimmt nicht überein');
        disableAll(false); message('Gespeichert und zurückgelesen. Kein Neustart ausgelöst.');
      } catch (e) {
        message(`Speicherstatus unklar: ${e.message}. Status neu lesen.`); byId('refresh').disabled = false;
      } finally { pending = false; }
    });
  }
  byId('filter-save').addEventListener('click', async () => {
    if (pending) return;
    let command;
    try { command = filterSaveCommand(byId('filter-packages').value); } catch(e) { message(e.message); return; }
    if (!scope.confirm('SUS_PATH-Ausnahmen speichern? Diese Apps dürfen registrierte Pfade sehen. Die Liste wirkt ab nächstem Boot, wenn die eigene SUS_PATH-Option und die bisherigen Freigaben eingeschaltet sind.')) return;
    pending = true; disableAll(true);
    try {
      await exec(command, scope);
      const report = JSON.parse(await exec(STATUS_COMMAND, scope));
      applySettings(report);
      if (filterSaveCommand(savedFilter) !== command) throw new Error('Paketliste nicht zurückgelesen');
      disableAll(false); message('Paketliste gespeichert und zurückgelesen. Anwendung beim nächsten Boot; keine Kernel-Änderung ausgeführt.');
    } catch(e) { message(`Speicherstatus unklar: ${e.message}. Status neu lesen.`); byId('refresh').disabled = false; }
    finally { pending = false; }
  });
  byId('refresh').addEventListener('click', refresh);
  return refresh();
}
if (typeof document !== 'undefined') start(document);
