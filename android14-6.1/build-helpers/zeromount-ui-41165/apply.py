#!/usr/bin/env python3
"""Integrate SUSFS/BRENE into the audited Guard6.13 WebUI, preserving backends."""
from pathlib import Path
import argparse
import hashlib
import json
import re

HERE = Path(__file__).resolve().parent
REVISION = 'sukisu41165-ui2'


def once(text, before, after):
    if after in text:
        return text
    if text.count(before) != 1:
        raise RuntimeError('Unexpected WebUI seam: ' + before[:100])
    return text.replace(before, after, 1)


def nav(active):
    tabs = [('susfs-brene.html', 'Übersicht'), ('susfs-rules.html', 'Regeln'),
            ('brene75.html', 'BRENE'), ('brene69.html', 'Patchdatum & Properties')]
    return '<nav class="zm-tabs" aria-label="SUSFS und BRENE">' + ''.join(
        f'<a href="./{path}"' + (' aria-current="page"' if path == active else '') + f'>{label}</a>'
        for path, label in tabs) + '</nav>'


def style_page(text, name):
    if f'<!-- {REVISION} -->' in text:
        return text
    text = re.sub(r'<style>.*?</style>', '', text, flags=re.S)
    text = once(text, '</head>', '<link rel="stylesheet" href="./assets/zm-susfs.css">'
                '<script type="module" src="./assets/zm-susfs-theme.mjs"></script></head>')
    text = once(text, '<body>', '<body class="zm-integrated">')
    # Replace the versioned page detours with the same navigation everywhere.
    text = re.sub(r'<header>.*?</header>',
                  '<header><a href="./index.html#settings">← ZeroMount Settings</a>'
                  '<span>SukiSU 41165 · Guard6.13</span></header>' + nav(name), text, count=1, flags=re.S)
    text = re.sub(r'<p style="padding:12px;[^>]*>.*?</p>', '', text, count=1, flags=re.S)
    if name == 'susfs-rules.html':
        text = text.replace('<nav><a href="./brene75.html">BRENE 0.0.75 & Kernel-Diagnose</a>', '<nav class="actions">')
    else:
        text = re.sub(r'<p><a href="./susfs-rules.html">.*?</p>', '', text, count=1, flags=re.S)
        text = re.sub(r'<p><a href="./brene75.html">.*?</p>', '', text, count=1, flags=re.S)
        text = re.sub(r'<p><a href="./brene69.html">.*?</p>', '', text, count=1, flags=re.S)
        text = text.replace('Ergänzungen zur bestehenden ZeroMount-Oberfläche.', 'Integrierte ZeroMount-Optionen.')
    if name == 'brene69.html':
        text = text.replace('ZeroMount · BRENE 68/69', 'ZeroMount · Patchdatum & Properties')
        text = text.replace('BRENE 0.0.68 + 0.0.69', 'Patchdatum & Properties')
    if name == 'brene75.html':
        text = text.replace('<h1>BRENE 0.0.75</h1>', '<h1>BRENE-Funktionen</h1>')
        text = text.replace('Neue BRENE-75-Optionen', 'BRENE 0.0.75')
    # No raw old page link should send users to a different visual shell.
    text = text.replace('./index.html"', './index.html#settings"')
    text = text.replace('ReSukiSU 35187', 'SukiSU 41165')
    return text.replace('</body>', f'<!-- {REVISION} --></body>')


def apply(module):
    module = Path(module).resolve()
    web = module / 'webroot'
    index = web / 'index.html'
    if not index.is_file():
        raise RuntimeError('Guard6.13 module webroot is required')
    changed = {}

    def put(path, text):
        data = text.encode('utf-8') if isinstance(text, str) else text
        if not path.exists() or path.read_bytes() != data:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            changed[path.relative_to(module).as_posix()] = hashlib.sha256(data).hexdigest()

    native = list((web / 'assets').glob('index-*.js'))
    native = [p for p in native if 'const [activeTab, setActiveTab]' in p.read_text(encoding='utf-8')]
    settings = [p for p in (web / 'assets').glob('SettingsTab-*.js')
                if 'function SusfsSection()' in p.read_text(encoding='utf-8')]
    if len(native) != 1 or len(settings) != 1:
        raise RuntimeError('Expected one audited native Settings and navigation asset')
    for path in (native[0], settings[0]):
        text = path.read_text(encoding='utf-8')
        if path == native[0]:
            text = once(text, "const [activeTab, setActiveTab] = createSignal('status');",
                        "const [activeTab, setActiveTab] = createSignal(globalThis.location?.hash === '#settings' ? 'settings' : 'status');")
        else:
            if "from './zm-susfs-menu.mjs'" not in text:
                text = "import { createSusfsEntry } from './zm-susfs-menu.mjs';\n" + text
            start = text.index('function SusfsSection()')
            end = text.index('\n}\n', start) + 3
            before, section, after = text[:start], text[start:end], text[end:]
            section = once(section, "insert(_el$, () => t('susfs.title'), null);", "insert(_el$, () => 'SUSFS & BRENE', null);")
            section = once(section, 'return _el$;\n      })(), (() => {', 'return _el$;\n      })(), createSusfsEntry(document), (() => {')
            section = section.replace("insert(_el$9, () => t('susfs.storageFilter'));", "insert(_el$9, () => 'Speicherordner filtern');")
            text = before + section + after
        put(path, text)

    text = index.read_text(encoding='utf-8')
    # The old fixed overlay obscured the native bottom navigation on the S24.
    text, count = re.subn(r'\s*<a href="\./susfs-rules\.html"[^>]*style="position:fixed;[^>]*>SUSFS & BRENE</a>', '', text)
    if not count and 'zm-susfs-menu.mjs' not in settings[0].read_text(encoding='utf-8'):
        raise RuntimeError('Unexpected floating-menu source')
    if './assets/zm-susfs.css' not in text:
        text = text.replace('</head>', '<link rel="stylesheet" href="./assets/zm-susfs.css"></head>')
    put(index, text)
    for name in ('susfs-rules.html', 'brene75.html', 'brene69.html'):
        path = web / name
        put(path, style_page(path.read_text(encoding='utf-8'), name))
    # Preserve old bookmarks; the duplicate versioned menu is no longer active.
    alias = '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=./brene75.html"><title>ZeroMount · BRENE</title></head><body><a href="./brene75.html">BRENE-Funktionen öffnen</a></body></html>\n'
    put(web / 'brene71.html', alias)
    put(web / 'susfs-brene.html', (HERE / 'susfs-brene.html').read_bytes())
    for name in ('zm-susfs.css', 'zm-susfs-theme.mjs', 'zm-susfs-menu.mjs', 'zm-susfs-hub.mjs'):
        put(web / 'assets' / name, (HERE / name).read_bytes())

    for name in ('brene75.mjs', 'brene69.mjs'):
        path = web / 'assets' / name
        text = path.read_text(encoding='utf-8')
        text = text.replace('Gerätetest noch nicht durchgeführt.', 'Status des installierten BRENE-Adapters gelesen.')
        text = text.replace('Zusätzliche BRENE-69-Lock-Properties', 'Zusätzliche Lock-Properties')
        text = text.replace('Kernel-Buildoption, kein bestätigter Laufzeit-Schalter.', 'Laufzeit-Schalter werden in SUSFS & BRENE → Kernel-Laufzeit separat auf ABI v1 geprüft.')
        put(path, text)
    return {'schema':1, 'revision':REVISION, 'changed_files_sha256':changed,
            'native_settings_entry':True, 'floating_overlay_removed':True,
            'backend_scripts_modified':False, 'saved_configuration_modified':False,
            'runtime_setters_require_owner_and_generation':True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    result = apply(args.module)
    if args.receipt:
        args.receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
