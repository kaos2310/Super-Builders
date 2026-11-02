// Additive UI: the existing Guard6.10 application assets are never rewritten.
export const KEYS = Object.freeze(['shrink_buffer_size','spoof_hosts','spoof_libstagefright','hide_lineage_strings','disable_child_process_restrictions','hide_ksu_directories','hide_third_party_apps']);
const BIN = '/data/adb/modules/meta-zeromount/bin/zm';
export const STATUS_COMMAND = `${BIN} brene75 status`;
const LABELS = [
 ['Logpuffer auf 64 KiB','logcat und persist.logd.size; Anwendung erst nach Boot-Abschluss.'],
 ['Stock-Hosts über OPEN_REDIRECT','App-Sicht für umounted UIDs ab 10000; ersetzt eine vorhandene Hosts-Filterung in dieser Sicht.'],
 ['libstagefright ausblenden','Optionale leere Dateisicht; kann Multimedia-Apps beeinträchtigen.'],
 ['LineageOS-Strings ausblenden','Optionale leere Sicht auf Policy-/Konfigurationsdateien für umounted Apps.'],
 ['Phantom-Prozessbeschränkung lockern','Android-Property; CPU- und PID-Kernel-Limits bleiben aus.'],
 ['KernelSU-Verzeichnisse verbergen','SuSFS-Dateisicht für die BRENE75-Paketliste; keine Ordnerlöschung.'],
 ['Drittanbieter-UIDs filtern','Ersetzt beim nächsten Boot die Priority-UID-Liste durch alle Drittanbieter-Apps. Nicht gleichzeitig mit einer eigenen Manager-Liste verwenden.'],
];
export function saveCommand(key, value) {
  if (!KEYS.includes(key) || typeof value !== 'boolean') throw new Error('Ungültige Einstellung');
  return `${BIN} brene75 set ${key} ${value ? 'true' : 'false'}`;
}
export function formatReport(report) {
 if (report.version !== '0.0.75') throw new Error('Unerwartete Adapterversion');
 return {kernel:'BRENE 0.0.75 · Guard6.13-Adapter\nGerätetest noch nicht durchgeführt.',peers:'UIDGate2, BootGuard2 und bestehende Writer-Adapter bleiben erhalten. Keine zweite BRENE-Installation erforderlich.',mounts:'Neue Umleitungen sind optional und prüfen SUSFS v2.3.0 sowie OPEN_REDIRECT. Bereits registrierte Regeln bleiben bis zum Neustart aktiv.'};
}
// KernelSU WebView's documented callback-shaped bridge, as shipped in the input.
let callbackId = 0;
export function execReadOrSave(command, scope = globalThis) {
  return new Promise((resolve, reject) => {
    if (typeof scope.ksu?.exec !== 'function') { reject(new Error('Root-Manager-WebView erforderlich')); return; }
    const name = `zm_brene75_${Date.now()}_${callbackId++}`;
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
  function disableAll(value) {
    byId('refresh').disabled = value;
    for (const input of inputs.values()) input.disabled = value;
  }
  function applySettings(report) {
    const settings = report.settings;
    if (settings?.error || !settings?.values) throw new Error(settings?.error || 'Konfiguration nicht lesbar');
    // Validate the entire response before enabling any mutation controls.
    for (const key of KEYS) if (!['true', 'false'].includes(settings.values[key])) throw new Error(`Ungültiger Wert: ${key}`);
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
  byId('refresh').addEventListener('click', refresh);
  return refresh();
}
if (typeof document !== 'undefined') start(document);
