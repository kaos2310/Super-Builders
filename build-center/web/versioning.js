// Arithmetic from the immutable upstream Kbuild. Never execute source text.
export const legacyFormula = Object.freeze({base:40000,offset:2815,operation:'-'});

export function versionCode(count, formula = legacyFormula) {
  if (!formula || Array.isArray(formula) || Object.keys(formula).sort().join(',') !== 'base,offset,operation'
      || !Number.isSafeInteger(count) || count < 1 || count > 2000000
      || !['base','offset'].every(k=>Number.isSafeInteger(formula[k])&&formula[k]>=0&&formula[k]<=1000000)
      || !['+','-'].includes(formula.operation)) throw new Error('Ungültige Quellen-/Versionsberechnung.');
  const code=formula.base+count+(formula.operation==='+'?formula.offset:-formula.offset);
  if (code<1 || code>2147483647) throw new Error('Ungültiges Ergebnis der Versionsberechnung.');
  return code;
}

export function readVersionFormula(text) {
  const formula={};
  for (const [name,key] of [['VERSION_BASE','base'],['VERSION_OFFSET','offset']]) {
    const matches=[...text.matchAll(new RegExp('^'+name+'\\s*:=\\s*([^\\r\\n]+)$','gm'))];
    if (matches.length!==1 || !/^[0-9]+\s*(?:#.*)?$/.test(matches[0][1]))
      throw new Error('SukiSU-Versionsangabe ist mehrdeutig: '+name);
    formula[key]=Number(matches[0][1].split('#')[0].trim());
  }
  const lines=[...text.matchAll(/^KSU_VERSION\s*:=\s*([^\r\n]+)$/gm)];
  if (lines.length!==1) throw new Error('SukiSU-Versionsformel ist mehrdeutig.');
  const arithmetic=String.raw`\$\(shell\s+expr\s+\$\(VERSION_BASE\)\s*\+\s*\$\(LOCAL_COUNT\)\s*([+-])\s*\$\(VERSION_OFFSET\)\s*\)`;
  const value=lines[0][1].split('#')[0].trim();
  const expression=value.match(new RegExp('^'+arithmetic+'$'))
    || value.match(new RegExp(String.raw`^\$\(if\s+\$\(LOCAL_COUNT\)\s*,\s*`+arithmetic+String.raw`\s*,\s*\$\(VERSION_BASE\)\s*\)$`));
  if (!expression) throw new Error('SukiSU-Versionsformel wird nicht unterstützt.');
  formula.operation=expression[1];versionCode(2000000,formula);return formula;
}

export function validateSourceVersion(source) {
  const formula=source?.sukisu_version_formula ?? legacyFormula;
  if (!Number.isSafeInteger(source?.sukisu_code) || versionCode(source?.sukisu_count,formula)!==source.sukisu_code)
    throw new Error('Quellen und Versionsberechnung stimmen nicht überein.');
  return formula;
}
