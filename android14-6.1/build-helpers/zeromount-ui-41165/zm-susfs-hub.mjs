const BIN = '/data/adb/modules/meta-zeromount/bin';
let serial = 0;
export function bridge(command, scope = globalThis) {
  return new Promise((resolve, reject) => {
    if (typeof scope.ksu?.exec !== 'function') return reject(new Error('Im Root-Manager öffnen'));
    const name = `zm_hub_${Date.now()}_${serial++}`;
    const cleanup = () => { clearTimeout(timer); delete scope[name]; };
    const timer = setTimeout(() => { cleanup(); reject(new Error('Zeitlimit; Status erneut lesen')); }, 15000);
    scope[name] = (code, stdout, stderr) => { cleanup(); Number(code) === 0 ? resolve(String(stdout)) : reject(new Error(String(stderr || stdout || `Exit ${code}`))); };
    try { scope.ksu.exec(command, '{}', name); } catch(error) { cleanup(); reject(error); }
  });
}
export const READ_COMMANDS = Object.freeze({owners:`${BIN}/zm switches`, runtime:`${BIN}/susfs-runtime status`, kernel:`${BIN}/zm brene-status`});
export const FEATURES = Object.freeze([
  {key:'uid-gating', bit:1, title:'UID-Gated Hiding', detail:'Wendet die bestehende UID-Freigabe auf die SUSFS-Verbraucher an. Aus verwendet deren bisheriges Verhalten.'},
  {key:'hidden-name', bit:2, title:'Hidden-Name-Filter', detail:'Pausiert oder aktiviert die vorhandenen Namensfilter; Einträge bleiben gespeichert.'},
  {key:'unicode-filter', bit:4, title:'Unicode-Filter', detail:'Pausiert oder aktiviert den vorhandenen Unicode-Namensfilter.'},
  {key:'symbol-hiding', bit:8, title:'Kernel-Symbole verbergen', detail:'Pausiert oder aktiviert den vorhandenen Symbolfilter.'},
]);
export function runtimeState(value) {
  const uint = n => Number.isInteger(n) && n >= 0 && n <= 0xffffffff;
  if (value?.protocol !== 'kaoslab-susfs-runtime' || value.version !== 1 || value.size !== 48 ||
      !uint(value.supported) || value.supported > 15 || !uint(value.enabled) ||
      (value.enabled & ~value.supported) !== 0 || !uint(value.generation) || value.generation === 0) throw new Error('Runtime ABI v1 nicht bestätigt');
  return value;
}
export function mayWrite(owner) {
  return owner?.schema === 2 && owner.susfs_enabled === true && owner.brene_enabled === true &&
    owner.susfs_effective === true && owner.brene_effective === true && owner.external_owner_active === false;
}
export function runtimeCommand(key, value, state, owner) {
  const feature = FEATURES.find(item => item.key === key); state = runtimeState(state);
  if (!feature || typeof value !== 'boolean' || !(state.supported & feature.bit) || !mayWrite(owner)) throw new Error('Laufzeit-Änderung durch Freigaben oder Kernel-Funktionen gesperrt');
  // Recheck the authoritative owner immediately before invoking the CAS setter.
  return `${BIN}/zm-susfs-owner allowed susfs && ${BIN}/zm-susfs-owner allowed brene && ${BIN}/susfs-runtime set ${key} ${value ? 1 : 0} ${state.generation}`;
}
export function startHub(doc, scope = globalThis, run = bridge) {
  const $ = id => doc.getElementById(id); const inputs = new Map();
  let busy = false, owner = null, state = null;
  const message = text => { $('message').textContent = text; };
  const controls = () => { $('refresh').disabled = busy; for (const feature of FEATURES) inputs.get(feature.key).disabled = busy || !state || !mayWrite(owner) || !(state.supported & feature.bit); };
  function render() {
    $('susfs-state').textContent = owner?.susfs_enabled ? (owner.susfs_effective ? 'Freigegeben' : 'Gespeichert, pausiert') : 'Pausiert';
    $('brene-state').textContent = owner?.brene_enabled ? (owner.brene_effective ? 'Freigegeben' : 'Gespeichert, pausiert') : 'Pausiert';
    $('owner-state').textContent = !owner ? 'Zuständigkeit nicht lesbar. Schreibzugriffe bleiben gesperrt.' : owner.external_owner_active ? 'Ein externer SUSFS-Verwalter ist aktiv. ZeroMount übernimmt keine parallelen Schreibzugriffe.' : 'Kein externer SUSFS-Verwalter gemeldet.';
    for (const feature of FEATURES) inputs.get(feature.key).checked = !!(state?.enabled & feature.bit);
    $('runtime-state').textContent = state ? `ABI v1 bestätigt · Generation ${state.generation}. ${mayWrite(owner) ? 'Änderungen sind freigegeben.' : 'Zum Ändern SUSFS und BRENE in ZeroMount freigeben; externe Zuständigkeit beachten.'}` : 'Runtime ABI v1 nicht verfügbar. Es werden keine Laufzeit-Schreibzugriffe angeboten.';
  }
  async function refresh() {
    if (busy) return; busy = true; state = null; owner = null; controls(); message('Lese aktuellen Status …');
    let kernelError = '';
    try {
      owner = JSON.parse(await run(READ_COMMANDS.owners, scope));
      if (owner?.schema !== 2 || ['susfs_enabled','brene_enabled','susfs_effective','brene_effective','external_owner_active'].some(key => typeof owner[key] !== 'boolean')) throw new Error('Freigabestatus nicht lesbar');
      try { state = runtimeState(JSON.parse(await run(READ_COMMANDS.runtime, scope))); } catch { state = null; }
      try {
        const report = JSON.parse(await run(READ_COMMANDS.kernel, scope)); const susfs = report.susfs ?? {};
        $('kernel-state').textContent = [`Kernel: ${report.kernel_release ?? 'unbekannt'}`, `SUSFS: ${susfs.kernel_reported_version ?? 'unbekannt'}`, ...(susfs.features ?? [])].join('\n');
        const policy = report.patch_date_policy ?? {};
        $('policy-state').textContent = [`Quelle: ${policy.source ?? 'nicht verfügbar'}`, `System: ${policy.os_target ?? 'nicht verfügbar'}`, `Vendor: ${policy.vendor_target ?? 'nicht verfügbar'}`].join('\n');
      } catch(e) { $('kernel-state').textContent = $('policy-state').textContent = 'Aktuelle Diagnose nicht verfügbar.'; kernelError = ` Diagnose nicht vollständig: ${e.message}`; }
      render(); message(`Status gelesen.${kernelError}`);
    } catch(e) { owner = null; state = null; render(); $('susfs-state').textContent = $('brene-state').textContent = 'Nicht lesbar'; message(`Fehler: ${e.message}`); }
    finally { busy = false; controls(); }
  }
  for (const feature of FEATURES) {
    const label = doc.createElement('label'); label.className = 'zm-runtime-row';
    const input = doc.createElement('input'); input.type = 'checkbox'; input.disabled = true; input.id = `runtime-${feature.key}`;
    const text = doc.createElement('span'); text.textContent = feature.title;
    const small = doc.createElement('small'); small.textContent = feature.detail; text.append(small); label.append(input, text); $('runtime-settings').append(label); inputs.set(feature.key, input);
    input.addEventListener('change', async () => {
      if (busy) return; const desired = input.checked; const previous = !!(state?.enabled & feature.bit);
      if (!scope.confirm(`${feature.title} für den aktuellen Boot ${desired ? 'aktivieren' : 'pausieren'}?`)) { input.checked = previous; return; }
      let command;
      try { command = runtimeCommand(feature.key, desired, state, owner); } catch(e) { input.checked = previous; message(e.message); return; }
      busy = true; controls();
      try {
        const updated = runtimeState(JSON.parse(await run(command, scope)));
        const verified = runtimeState(JSON.parse(await run(READ_COMMANDS.runtime, scope)));
        if (updated.generation !== verified.generation || updated.enabled !== verified.enabled || !!(verified.enabled & feature.bit) !== desired) throw new Error('Laufzeit-Änderung nicht zurückgelesen');
        state = verified; render(); message('Laufzeit-Änderung bestätigt. Gespeicherte Regeln bleiben erhalten.');
      } catch(e) { state = null; message(`Status unklar: ${e.message}. Bitte Status aktualisieren.`); }
      finally { busy = false; controls(); }
    });
  }
  $('refresh').addEventListener('click', refresh); return refresh();
}
if (typeof document !== 'undefined' && document.getElementById('runtime-settings')) startHub(document);
