#!/usr/bin/env python3
"""Reproduce the user's Guard6.13 ZIP plus a bounded BRENE71 integration."""
import argparse,hashlib,json,zipfile,stat
from pathlib import Path, PurePosixPath, PureWindowsPath
HERE=Path(__file__).resolve().parent
PIN='ffa00c0700604216de8a86ad9c74226af1add0d5'
INPUTS={'BRENE-v0.0.71.zip':'182a03f9d0b76062ed303c2d0cdfcc6eac275c8f0aafad8ae1287a92e939f97d','ZeroMount-v2.0.216-dev.guard6.13.brene69.susfs230-r3.3.uidgate2.bootguard2-BakaSU-35215-arm64.zip':'5eb8e7fc65eeebd25525a4de1d1cdada9c27a0667401d99ab37435470a2f0895'}
def sha(data):return hashlib.sha256(data).hexdigest()
def entries(path):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:raise RuntimeError('Input ZIP CRC failure')
        result={}
        for item in archive.infolist():
            name=PurePosixPath(item.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in item.filename or ':' in item.filename or stat.S_ISLNK(item.external_attr>>16):raise RuntimeError('Unsafe ZIP entry')
            if not item.is_dir():
                if item.filename in result:raise RuntimeError('Duplicate ZIP entry')
                result[item.filename]=(archive.read(item),item.external_attr)
        return result
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-zip',type=Path,required=True);p.add_argument('--brene-zip',type=Path,required=True);p.add_argument('--inventory',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True)
    a=p.parse_args();inventory=json.loads(a.inventory.read_text(encoding='utf-8'))
    expected={PureWindowsPath(item['file']).name:item['sha256'] for item in inventory}
    assert expected==INPUTS,'Input inventory drift'
    for path in (a.base_zip,a.brene_zip):
        if sha(path.read_bytes())!=expected[path.name]:raise RuntimeError('Pinned input digest mismatch: '+path.name)
    base=entries(a.base_zip);brene=entries(a.brene_zip)
    assert b'version=v0.0.71' in brene['module.prop'][0]
    core=base['bin/arm64-v8a/zeromount'][0]
    assert core[:6]==b'\x7fELF\x02\x01' and int.from_bytes(core[18:20],'little')==183
    assert sha(core)=='1a0b25246a54746ebe89fb210ffbc8217f6227d9f5a04e964630e50228bea036'
    assert b'KSU_SUKISU' in core
    result=dict(base);changed={}
    def put(name,data,executable=False):
        if isinstance(data,str):data=data.encode('utf-8')
        result[name]=(data,(0o100755 if executable else 0o100644)<<16);changed[name]=sha(data)
    version='v2.0.216-dev.guard6.13.brene71.susfs230-r3.3.uidgate2.bootguard2.sukisu41013'
    prop=base['module.prop'][0].decode()
    lines=[]
    for line in prop.splitlines():
        if line.startswith('version='):line='version='+version
        elif line.startswith('versionCode='):line='versionCode=2021625'
        elif line.startswith('description='):line='description=Guard6.13 + BRENE 0.0.71 adapter, UIDGate2, BootGuard2, DroidSpaces VFS, OPEN_REDIRECT; SukiSU 41013 / SUSFS 2.3.0 / S928B EZIF. Device test pending.'
        lines.append(line)
    put('module.prop','\n'.join(lines)+'\n')
    put('bin/zm-brene71',(HERE/'zm-brene71').read_bytes(),True)
    wrapper=base['bin/zm'][0].decode()
    anchor='case "$_dispatch" in\n    mount)'
    assert wrapper.count(anchor)==1
    wrapper=wrapper.replace(anchor,'''case "$_dispatch" in
    brene71)
        shift; exec "$BINDIR/zm-brene71" "$@"
        ;;
    prop-watch)
        shift; exec "$BINDIR/zm-brene71" prop-watch "$@"
        ;;
    mount)''')
    put('bin/zm',wrapper,True)
    for name in ('service.sh','boot-completed.sh'):
        text=base[name][0].decode();assert '"$BIN" prop-watch' in text
        text=text.replace('"$BIN" prop-watch','"$MODDIR/bin/zm" prop-watch')
        if name=='boot-completed.sh':
            text+='\n# BRENE71 optional features share the existing late boot callback.\n"$MODDIR/bin/zm" brene71 late > /data/adb/zeromount/.brene71-late.log 2>&1 || echo "zeromount: BRENE71 feature pending/failed; inspect .brene71-late.log" > /dev/kmsg 2>/dev/null\n'
        put(name,text,True)
    # Install checks run before the inherited installer writes state or peer adapters.
    install=base['customize.sh'][0].decode()
    guard='''# This package targets the official SukiSU manager and the audited SUSFS ABI.
[ "$KSU" = true ] && [ "$KSU_SUKISU" = true ] || abort "SukiSU manager required for this package"
_zm71_ksud=/data/adb/ksud
[ -x "$_zm71_ksud" ] || _zm71_ksud=/data/adb/ksu/bin/ksud
[ "$("$_zm71_ksud" susfs show version 2>/dev/null)" = v2.3.0 ] || abort "Exact SUSFS v2.3.0 required"
unset _zm71_ksud
'''
    # KSU env values are supplied by the manager before customize.sh starts.
    at=install.find('\n',install.index('#!'))+1
    put('customize.sh',install[:at]+guard+install[at:],True)
    html=base['webroot/brene69.html'][0].decode()
    html=html.replace('BRENE 68/69','BRENE 0.0.71').replace('BRENE 0.0.68 + 0.0.69','BRENE 0.0.71').replace('brene69.mjs','brene71.mjs')
    html=html.replace('Optionale Property-Anpassungen','Neue BRENE-71-Optionen')
    html=html.replace('<p>Ergänzungen zur bestehenden ZeroMount-Oberfläche.', '<p><a href="./brene69.html">Bestehende Patchdatum- und Lock-Schalter</a> · <a href="https://github.com/longze777/UID-" target="_blank" rel="noopener noreferrer">UID Filter (BRENE-Empfehlung)</a></p><p>Ergänzungen zur bestehenden ZeroMount-Oberfläche.')
    html=html.replace("connect-src 'none';", "connect-src 'none';")
    html=html.replace('Neue Schalter sind standardmäßig aus.','Der 64-KiB-Logpuffer ist wie in BRENE 71 standardmäßig aktiv; weitere neue Schalter sind aus.')
    html=html.replace('Kernel, SUSFS und UID-Gated Hiding','BRENE-Adapter').replace('Weitere SUSFS-Module','Integration').replace('Auffällige Mount-Einträge','OPEN_REDIRECT')
    put('webroot/brene71.html',html)
    script=base['webroot/assets/brene69.mjs'][0].decode()
    start=script.index('export const KEYS');end=script.index('export function saveCommand')
    script=script[:start]+'''export const KEYS = Object.freeze(['shrink_buffer_size','spoof_hosts','spoof_libstagefright','hide_lineage_strings','disable_child_process_restrictions']);
const BIN = '/data/adb/modules/meta-zeromount/bin/zm';
export const STATUS_COMMAND = `${BIN} brene71 status`;
const LABELS = [
 ['Logpuffer auf 64 KiB','logcat und persist.logd.size; Anwendung erst nach Boot-Abschluss.'],
 ['Stock-Hosts über OPEN_REDIRECT','App-Sicht für umounted UIDs ab 10000; ersetzt eine vorhandene Hosts-Filterung in dieser Sicht.'],
 ['libstagefright ausblenden','Optionale leere Dateisicht; kann Multimedia-Apps beeinträchtigen.'],
 ['LineageOS-Strings ausblenden','Optionale leere Sicht auf Policy-/Konfigurationsdateien für umounted Apps.'],
 ['Phantom-Prozessbeschränkung lockern','Android-Property; CPU- und PID-Kernel-Limits bleiben aus.'],
];
''' +script[end:]
    script=script.replace('config set brene.${key}', 'brene71 set ${key}')
    start=script.index('export function formatReport');end=script.index('// KernelSU WebView',start)
    script=script[:start]+'''export function formatReport(report) {
 if (report.version !== '0.0.71') throw new Error('Unerwartete Adapterversion');
 return {kernel:'BRENE 0.0.71 · Guard6.13-Adapter\\nGerätetest noch nicht durchgeführt.',peers:'UIDGate2, BootGuard2 und bestehende Writer-Adapter bleiben erhalten. Keine zweite BRENE-Installation erforderlich.',mounts:'Neue Umleitungen sind optional und prüfen SUSFS v2.3.0 sowie OPEN_REDIRECT. Bereits registrierte Regeln bleiben bis zum Neustart aktiv.'};
}
''' +script[end:]
    script=script.replace('zm_brene69_','zm_brene71_')
    put('webroot/assets/brene71.mjs',script)
    html=base['webroot/brene69.html'][0].decode().replace('<h1>BRENE','<p><a href="./brene71.html">Neue BRENE-71-Optionen →</a></p><h1>BRENE')
    put('webroot/brene69.html',html)
    for name in ('webroot/index.html','webroot/susfs-rules.html'):
        text=base[name][0].decode().replace('brene69.html','brene71.html').replace('BRENE 68/69','BRENE 0.0.71');put(name,text)
    manifest={'schema':3,'version':version,'baseline_kernel_run':39061619013,'sukisu_version':41013,'sukisu_commit':PIN,'uapi_version':6,'susfs_version':'v2.3.0','susfs_commit':'5369359dbd10f6dd8cbdd59d1df7b788b29b168c','target':'SM-S928B / S928BXXU6EZIF / EUX / 6.1.162','inputs':{path.name:sha(path.read_bytes()) for path in (a.base_zip,a.brene_zip)},'native_core_sha256':sha(core),'native_core_modified':False,'historical_manifest':'build-manifest-before-brene71.json','changed_files_sha256':changed,'device_tested':False,'ci_result_at_packaging':'not observed','automatic_updates':False,'standalone_brene_boot_scripts_executed':False}
    put('build-manifest-before-brene71.json',base['build-manifest.json'][0])
    put('BRENE71-UPSTREAM-INPUT.json',json.dumps({'version':'0.0.71','sha256':sha(a.brene_zip.read_bytes()),'files_sha256':{name:sha(data) for name,(data,_) in brene.items()}},indent=2)+'\n')
    put('README-BRENE71-SukiSU41013.md',(HERE/'README.md').read_bytes())
    # Avoid inheriting an old current-state claim. History remains in the named receipt.
    put('build-manifest.json',json.dumps(manifest,indent=2)+'\n')
    # Regenerate every checksum after all content changes. Runtime-mutated files
    # remain excluded from installed integrity checks as in the original package.
    runtime={'module.prop','webroot/cache.json','webroot/zm-init.js'}
    for name in ('SHA256SUMS','COMPAT-SHA256SUMS'):
        sums=''.join(sha(data)+'  '+key+'\n' for key,(data,_) in sorted(result.items()) if key not in ('SHA256SUMS','COMPAT-SHA256SUMS') and (name=='SHA256SUMS' or key not in runtime))
        put(name,sums)
    a.output_dir.mkdir(parents=True,exist_ok=True)
    output=a.output_dir/'ZeroMount-Guard6.13-BRENE-0.0.71-SukiSU-41013-arm64.zip'
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,(data,mode) in sorted(result.items()):
            item=zipfile.ZipInfo(name,(2026,10,18,0,0,0));item.create_system=3;item.external_attr=mode;item.compress_type=zipfile.ZIP_DEFLATED;z.writestr(item,data)
    with zipfile.ZipFile(output) as z:
        assert z.testzip() is None and z.read('bin/arm64-v8a/zeromount')==core
        for line in z.read('SHA256SUMS').decode().splitlines():
            digest,name=line.split('  ',1);assert sha(z.read(name))==digest,name
    preserved={name:sha(data) for name,(data,_) in base.items() if name not in changed and name not in ('SHA256SUMS','COMPAT-SHA256SUMS')}
    receipt={'output':str(output),'sha256':sha(output.read_bytes()),'size':output.stat().st_size,'archive_crc_passed':True,'all_checksums_passed':True,'preserved_files_sha256':preserved,'changed_files_sha256':changed,'native_core_byte_identical':True,'device_tested':False}
    (a.output_dir/'PACKAGE-VERIFICATION.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in receipt.items() if not isinstance(v,dict)},indent=2))
if __name__=='__main__':main()
