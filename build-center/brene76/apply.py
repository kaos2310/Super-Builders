"""Add the reviewed BRENE76 delta to the complete Guard6 package in memory."""
from pathlib import Path
import hashlib,json,re,struct,zipfile

HERE=Path(__file__).resolve().parent
UPSTREAM_SHA='9932421b98ba71b00d500cd1ee944705f0ab2f78ee7c6fbef281bfee4b6f7a8c'

def sha(data):return hashlib.sha256(data).hexdigest()

def apply(members,tool,expected_source,source_root):
    original=dict(members)
    archive=(HERE/'BRENE-v0.0.76.zip').read_bytes()
    receipt=json.loads((HERE/'UPSTREAM.json').read_text())
    if sha(archive)!=UPSTREAM_SHA or receipt['archive_sha256']!=UPSTREAM_SHA:
        raise RuntimeError('Reviewed BRENE76 input archive drift')
    with zipfile.ZipFile(HERE/'BRENE-v0.0.76.zip') as source:
        if source.testzip() or set(source.namelist())!=set(receipt['files_sha256']):
            raise RuntimeError('BRENE76 upstream archive manifest/CRC mismatch')
        for name,digest in receipt['files_sha256'].items():
            if sha(source.read(name))!=digest:raise RuntimeError('BRENE76 upstream member drift: '+name)
    raw=tool.read_bytes()
    proof=json.loads((tool.parent/'SUSFS-TOOL-BUILD.json').read_text())
    if (proof.get('repository')!='https://gitlab.com/simonpunk/susfs4ksu' or
        proof.get('pin')!='f76b81f2a6bf98e4029cc0c823c054edbec29803' or
        proof.get('sha256')!=sha(raw) or proof.get('bytes')!=len(raw) or
        proof.get('target')!='aarch64-linux-android26' or
        proof.get('built_from_official_c_sources') is not True or
        proof.get('source_files_sha256')!=expected_source.get('source_files_sha256') or
        expected_source.get('pin')!=proof.get('pin') or
        not proof.get('source_files_sha256',{}).get('features/sus_path_uid_filter.c')):
        raise RuntimeError('Matching fresh SUSFS source-to-binary build proof required')
    members['SUSFS-TOOL-BUILD.json']=(json.dumps(proof,indent=2)+'\n').encode()
    if raw[:6]!=b'\x7fELF\x02\x01' or len(raw)<64 or struct.unpack_from('<H',raw,18)[0]!=183:
        raise RuntimeError('Private SUSFS tool must be a real Android AArch64 ELF')
    members['bin/ksu_susfs']=raw
    for name,digest in expected_source['source_files_sha256'].items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name:
            raise RuntimeError('Unsafe official tool source path')
        data=(source_root/relative).read_bytes()
        if sha(data)!=digest:raise RuntimeError('Official tool source changed: '+name)
        members['source/ksu_susfs/'+name]=data
    members['bin/zm-brene76']=(HERE/'zm-brene76').read_bytes()
    # Boot hooks and old command/bookmark paths keep their original contract.
    members['bin/zm-brene75']=b'#!/system/bin/sh\nexec "${0%/*}/zm-brene76" "$@"\n'
    wrapper=members['bin/zm'].decode()
    before='    brene71|brene75)'
    if wrapper.count(before)!=1:raise RuntimeError('Unknown Guard6 BRENE dispatcher seam')
    members['bin/zm']=wrapper.replace(before,'    brene71|brene75|brene76)',1).encode()
    members['webroot/assets/brene76.mjs']=(HERE/'brene76.mjs').read_bytes()
    members['webroot/assets/brene75.mjs']=b"export * from './brene76.mjs';\n"
    page=members['webroot/brene75.html'].decode().replace('brene75.mjs','brene76.mjs')
    page=page.replace('BRENE 0.0.75','BRENE 0.0.76').replace('BRENE 75','BRENE 76')
    marker='    <div id="settings"></div>'
    if page.count(marker)!=1:raise RuntimeError('Unknown Guard6 BRENE form seam')
    page=page.replace(marker,marker+'''
    <h3>SUS_PATH: Apps mit sichtbaren Pfaden</h3>
    <p>Kommagetrennte Paketnamen. Diese Apps dürfen registrierte SUS_PATH-Pfade sehen; alle anderen App-UIDs behalten die verborgene Sicht. Eine leere Liste entfernt die Ausnahmen. Die Priority-UID-Liste ist eine eigene Funktion.</p>
    <label for="filter-packages">Paketnamen</label><textarea id="filter-packages" rows="4" disabled autocomplete="off" spellcheck="false" aria-describedby="filter-help"></textarea>
    <p id="filter-help">Speichert nur die Liste. Sie wird beim nächsten Boot angewendet, wenn die eigene SUS_PATH-Option und die bestehenden SUSFS-/BRENE-Freigaben aktiv sind. Der neue Kernelbefehl hat keine Listen-Rücklesefunktion; ein gespeicherter Wert bestätigt noch keine Anwendung.</p>
    <button id="filter-save" type="button" disabled>Paketliste speichern</button>
''')
    page=page.replace('weitere neue Schalter sind aus','zusätzliche Schalter sind standardmäßig aus; bereits gespeicherte Werte bleiben erhalten')
    members['webroot/brene75.html']=page.encode()
    members['webroot/brene76.html']=page.encode()
    for name in list(members):
        if name.startswith('webroot/assets/SettingsTab-') and name.endswith('.js'):
            # Text labels only; every inherited native setting and handler stays.
            members[name]=members[name].replace(b'BRENE 75',b'BRENE 76')
    members['customize.sh']=members['customize.sh'].replace(b'BRENE75',b'BRENE76').replace(b'SukiSU35004',b'SukiSU Nova35004')
    for name in list(members):
        if name.startswith('webroot/') and name.endswith('.html'):
            text=members[name].decode()
            text=text.replace('./brene75.html','./brene76.html')
            text=re.sub(r'SukiSU\s+[0-9]+\s*·\s*Guard6\.13','SukiSU Nova 35004 · Guard6.13',text)
            members[name]=text.encode()
    # Keep the input inert. No original BRENE hook, global tool replacement,
    # deletion script or second standalone WebUI enters Guard's boot path.
    members['upstream/BRENE-v0.0.76.zip']=archive
    members['BRENE76-DELTA-75-76.json']=(HERE/'DELTA-75-76.json').read_bytes()
    members['BRENE76-UPSTREAM-INPUT.json']=(json.dumps(receipt,indent=2)+'\n').encode()
    changed={name:sha(raw) for name,raw in members.items() if original.get(name)!=raw}
    result={'schema':1,'version':'0.0.76','upstream_archive_sha256':UPSTREAM_SHA,
        'changed_files_sha256':changed,'private_susfs_tool_sha256':sha(members['bin/ksu_susfs']),
        'standalone_scripts_executed':False,'standalone_hooks_installed':False,
        'saved_state_directory':'/data/adb/zeromount/brene71',
        'previous_option_keys_preserved':True,'additional_options_default_enabled':False,
        'new_features':['sus_path_uid_filter','hide_all_apps_with_uid_10000_and_above','hide_vector_injection','hide_oem_unlocking_toggle','sanitize_build_fingerprint'],
        'sus_path_uid_filter_semantics':'allow-list of apps that may see registered SUS_PATH paths; comma clears',
        'sus_path_uid_filter_kernel_getter_available':False,'application':'next_boot',
        'preserved_75_behavior':['existing logcat and persist.logd.size buffer control','all seven existing saved options','original rules/properties/ownership/boot hooks'],
        'runtime_menu_additive':True,'device_runtime_tested':False}
    members['BRENE76-INTEGRATION.json']=(json.dumps(result,indent=2)+'\n').encode()
    return result
