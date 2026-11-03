#!/usr/bin/env python3
"""Reproducible Guard6.13 + BRENE75 package from the exact user inputs."""
from pathlib import Path,PurePosixPath
import argparse,zipfile,hashlib,json,stat
HERE=Path(__file__).resolve().parent
INPUTS={'BRENE-v0.0.75.zip':'dd5238d64ff71bdf4356e232a625752160964e236e7e8f237c3c006a2e2f1ae3','ZeroMount-Guard6.13-BRENE-0.0.71-SukiSU-41013-arm64.zip':'93e41c4419e3d808ea89314e61f7819dc3b2c1604b21fdb74ca8687968d62309'}
def sha(d):return hashlib.sha256(d).hexdigest()
def read_zip(path):
    if path.name not in INPUTS or sha(path.read_bytes())!=INPUTS[path.name]:raise RuntimeError('Exact input ZIP required')
    out={}
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:raise RuntimeError('Input CRC failure')
        for item in z.infolist():
            p=PurePosixPath(item.filename)
            if p.is_absolute() or '..' in p.parts or ':' in item.filename or '\\' in item.filename or stat.S_ISLNK(item.external_attr>>16):raise RuntimeError('Unsafe archive path')
            if not item.is_dir():
                if item.filename in out:raise RuntimeError('Duplicate archive entry')
                out[item.filename]=(z.read(item),item.external_attr)
    return out
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-zip',type=Path,required=True);p.add_argument('--brene-zip',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
    base=read_zip(a.base_zip);brene=read_zip(a.brene_zip)
    assert b'version=v0.0.75' in brene['module.prop'][0]
    core=base['bin/arm64-v8a/zeromount'][0]
    assert core[:6]==b'\x7fELF\x02\x01' and int.from_bytes(core[18:20],'little')==183
    assert sha(core)=='1a0b25246a54746ebe89fb210ffbc8217f6227d9f5a04e964630e50228bea036'
    out=dict(base);changed={}
    def put(name,data,executable=False):
        if isinstance(data,str):data=data.encode('utf-8')
        out[name]=(data,(0o100755 if executable else 0o100644)<<16);changed[name]=sha(data)
    version='v2.0.216-dev.guard6.13.brene75.susfs230.uidgate2.bootguard2.sukisu41141'
    prop=base['module.prop'][0].decode()
    lines=[]
    for line in prop.splitlines():
        if line.startswith('version='):line='version='+version
        elif line.startswith('versionCode='):line='versionCode=2026110301'
        elif line.startswith('description='):line='description=Guard6.13 + BRENE 0.0.75, optional priority UID filtering and non-destructive directory views; SukiSU 41141 / SUSFS 2.3.0 / S928B EZIF. Device test pending.'
        lines.append(line)
    put('module.prop','\n'.join(lines)+'\n')
    put('bin/zm-brene75',(HERE/'zm-brene75').read_bytes(),True)
    put('bin/zm-brene71','#!/system/bin/sh\nexec "${0%/*}/zm-brene75" "$@"\n',True)
    wrapper=base['bin/zm'][0].decode()
    wrapper=wrapper.replace('    brene71)\n        shift; exec "$BINDIR/zm-brene71"', '    brene71|brene75)\n        shift; exec "$BINDIR/zm-brene75"').replace('exec "$BINDIR/zm-brene71" prop-watch','exec "$BINDIR/zm-brene75" prop-watch')
    old='    _features=$("$_ksud" susfs show enabled_features 2>/dev/null) || return 1'
    assert wrapper.count(old)==1
    wrapper=wrapper.replace(old,'    _features=$("$_ksud" susfs features 2>/dev/null) || return 1\n    _features=$(printf \'%s\\n\' "$_features" | tr \',\\r\' \'\\n\\n\' | sed \'s/^[[:space:]]*//;s/[[:space:]]*$//\')')
    put('bin/zm',wrapper,True)
    install=base['customize.sh'][0].decode();a0=install.index('# This package targets');b0=install.index('# ZeroMount install hook')
    guard='''# Official SukiSU + compatible SUSFS ABI; native susfs-compat gate remains below.
[ "$KSU" = true ] && [ "$KSU_SUKISU" = true ] || abort "SukiSU manager required for this package"
_zm75_ksud=/data/adb/ksud
[ -x "$_zm75_ksud" ] || _zm75_ksud=/data/adb/ksu/bin/ksud
_zm75_version=$("$_zm75_ksud" susfs version 2>&1) || abort "SukiSU SUSFS version query failed: $_zm75_version"
[ "$_zm75_version" = v2.3.0 ] || abort "SUSFS v2.3.0 required; reported: ${_zm75_version:-empty}"
unset _zm75_ksud _zm75_version
'''
    put('customize.sh',install[:a0]+guard+install[b0:],True)
    put('META-INF/com/google/android/update-binary',base['META-INF/com/google/android/update-binary'][0].replace(b'\r\n',b'\n'),True)
    for name in ('service.sh','boot-completed.sh'):
        text=base[name][0].decode().replace('"$BIN" prop-watch','"$MODDIR/bin/zm" prop-watch').replace('brene71 late','brene75 late').replace('.brene71-late.log','.brene75-late.log')
        put(name,text,True)
    put('webroot/assets/brene75.mjs',(HERE/'brene75.mjs').read_bytes())
    put('webroot/brene75.html',(HERE/'brene75.html').read_bytes())
    put('webroot/brene71.html',(HERE/'brene75.html').read_bytes())
    for name in ('webroot/index.html','webroot/susfs-rules.html','webroot/brene69.html'):
        text=base[name][0].decode().replace('brene71.html','brene75.html').replace('BRENE 0.0.71','BRENE 0.0.75').replace('BRENE-71','BRENE-75')
        put(name,text)
    put('build-manifest-before-brene75.json',base['build-manifest.json'][0])
    put('BRENE75-UPSTREAM-INPUT.json',json.dumps({'version':'0.0.75','authors':'rrr333nnn333, simonpunk, KOWX712','archive_sha256':INPUTS[a.brene_zip.name],'files_sha256':{n:sha(d) for n,(d,_) in brene.items()},'standalone_scripts_executed':False},indent=2)+'\n')
    put('README-BRENE75-SukiSU41141.md',(HERE/'README.md').read_bytes())
    manifest={'schema':4,'version':version,'sukisu_version':41141,'sukisu_commit':'b9fcdc05f94c8fdab1a5657db68e67bac3942020','susfs_version':'v2.3.0','priority_filter_upstream_commit':'a0ac906915c8a8d50d474dfb3cae478ef32edc1a','config_required':['CONFIG_KSU_SUSFS','CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER','CONFIG_ZEROMOUNT','CONFIG_KSU_SUSFS_OPEN_REDIRECT','CONFIG_KSU_SUSFS_UID_GATED_HIDING'],'uapi_version':6,'target':'SM-S928B / S928BXXU6EZIF / EUX / Linux 6.1.162','inputs':INPUTS,'native_core_sha256':sha(core),'native_core_modified':False,'changed_files_sha256':dict(changed),'device_tested':False,'new_features_default_enabled':False,'existing_config_path':'/data/adb/zeromount/brene71/options','directory_delete_script_imported':False,'automatic_module_installation':False}
    put('build-manifest.json',json.dumps(manifest,indent=2)+'\n')
    runtime={'module.prop','webroot/cache.json','webroot/zm-init.js'}
    for name in ('SHA256SUMS','COMPAT-SHA256SUMS'):
        sums=''.join(sha(data)+'  '+key+'\n' for key,(data,_) in sorted(out.items()) if key not in ('SHA256SUMS','COMPAT-SHA256SUMS') and (name=='SHA256SUMS' or key not in runtime))
        put(name,sums)
    a.output_dir.mkdir(parents=True,exist_ok=True);target=a.output_dir/'ZeroMount-Guard6.13-BRENE-0.0.75-SukiSU-41141-arm64.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,(data,mode) in sorted(out.items()):
            info=zipfile.ZipInfo(name,(2026,11,2,0,0,0));info.create_system=3;info.external_attr=mode;info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,data)
    with zipfile.ZipFile(target) as z:
        assert z.testzip() is None and z.read('bin/arm64-v8a/zeromount')==core
        for line in z.read('SHA256SUMS').decode().splitlines():
            digest,name=line.split('  ',1);assert sha(z.read(name))==digest,name
    unchanged={n:sha(d) for n,(d,_) in base.items() if n not in changed and n not in ('SHA256SUMS','COMPAT-SHA256SUMS')}
    receipt={'output':target.name,'sha256':sha(target.read_bytes()),'bytes':target.stat().st_size,'archive_crc_passed':True,'all_checksums_passed':True,'native_core_byte_identical':True,'unchanged_files_sha256':unchanged,'changed_files_sha256':changed,'device_tested':False}
    (a.output_dir/'PACKAGE-VERIFICATION.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if not isinstance(v,dict)},indent=2))
if __name__=='__main__':main()
