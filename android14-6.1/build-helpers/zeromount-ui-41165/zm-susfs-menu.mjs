// Native Settings entry. No shell commands or settings writes occur on render.
export function createSusfsEntry(doc = document) {
  const row = doc.createElement('a');
  row.href = './susfs-brene.html';
  row.className = 'settings__item zm-integration-entry';
  const content = doc.createElement('div'); content.className = 'settings__item-content';
  const title = doc.createElement('div'); title.className = 'settings__item-label';
  title.textContent = 'SUSFS & BRENE verwalten →';
  const description = doc.createElement('div'); description.className = 'settings__item-desc';
  description.textContent = 'Kernel-Laufzeit, eigene Regeln, BRENE-Optionen und Patchdatum in einer Oberfläche.';
  content.append(title, description); row.append(content); return row;
}
