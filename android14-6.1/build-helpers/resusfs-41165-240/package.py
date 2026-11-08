#!/usr/bin/env python3
"""Package the preserved ReSuSFS module with source-built SUSFS and Runtime v1."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,struct,zipfile
HERE=Path(__file__).resolve().parent
NAME='ReSuSFS-v26.10.23-KAOSLAB-SUSFS2.4.0-Runtime1-SukiSU41165-arm64.zip'
def sha(data):return hashlib.sha256(data).hexdigest()
def arm64(data):return data[:6]==b'\x7fELF\x02\x01' and struct.unpack_from('<H',data,18)[0]==183
def once(text,old,new):
 if text.count(old)!=1:raise RuntimeError('Baseline anchor changed: '+old[:70])
 return text.replace(old,new,1)
def package(runtime_helper,susfs_tool,output):
 base=json.loads((HERE/'BASE.json').read_text());archive=(HERE/'module-base.zip').read_bytes()
 if sha(archive)!=base['sha256']:raise RuntimeError('Preserved ReSuSFS baseline changed')
 runtime=runtime_helper.read_bytes();tool=susfs_tool.read_bytes()
 if not arm64(runtime) or not arm64(tool):raise RuntimeError('Real AArch64 binaries required')
 if any(label not in runtime for label in (b'kaoslab-susfs-runtime',b'uid-gating',b'hidden-name',b'unicode-filter',b'symbol-hiding')):raise RuntimeError('Runtime helper contract strings missing')
 source=json.loads((HERE/'SOURCE.json').read_text());build=json.loads((susfs_tool.parent/'SUSFS-TOOL-BUILD.json').read_text())
 if build.get('sha256')!=sha(tool) or build.get('pin')!=source['pin'] or build.get('source_files_sha256')!=source['source_files_sha256'] or build.get('built_from_official_c_sources') is not True:raise RuntimeError('Official SUSFS C build receipt mismatch')
 files={}
 with zipfile.ZipFile(HERE/'module-base.zip') as z:
  if z.testzip() is not None:raise RuntimeError('Baseline ZIP CRC failure')
  for item in z.infolist():
   path=PurePosixPath(item.filename)
   if item.is_dir():continue
   if path.is_absolute() or '..' in path.parts or '\\' in item.filename:raise RuntimeError('Unsafe baseline path')
   data=z.read(item)
   if sha(data)!=base['files_sha256'][item.filename]:raise RuntimeError('Baseline member changed')
   files[item.filename]=data
 original=dict(files)
 def put(name,data):files[name]=data.encode() if isinstance(data,str) else data
 put('module.prop','id=ReSuSFS\nname=ReSuSFS\nversion=v26.10.23.kaoslab.susfs240.runtime1.sukisu41165\nversionCode=2026110802\nauthor=ahmed-alnassif; KAOSLAB integration\ndescription=ReSuSFS + SUSFS 2.4.0 + four Runtime v1 controls + Priority UID; existing profiles retained.\n')
 put('bin/ksu_susfs',tool);put('bin/susfs-runtime',runtime)
 for name in ('resusfs-control','resusfs-susfs'):put('bin/'+name,(HERE/name).read_bytes())
 put('bin/ReSuSFS','#!/system/bin/sh\nexec sh /data/adb/modules/ReSuSFS/ReSuSFS.sh "$@"\n')
 put('customize.sh',(HERE/'customize.sh').read_bytes())
 text=files['ReSuSFS.sh'].decode()
 text=once(text,'PATH=/data/adb/ksu/bin:/data/data/com.termux/files/usr/bin:$PATH','PATH=/data/adb/modules/ReSuSFS/bin:/data/adb/ksu/bin:/data/data/com.termux/files/usr/bin:$PATH')
 text=once(text,'SUSFS_BIN=/data/adb/ksu/bin/ksu_susfs','SUSFS_BIN=/data/adb/modules/ReSuSFS/bin/resusfs-susfs')
 text=once(text,'SUSFS_MIN_VERSION="v2.2.0"','SUSFS_MIN_VERSION="v2.3.0"')
 anchor='[ ! -d "$PERSISTENT_DIR" ] && mkdir -p "$PERSISTENT_DIR"'
 early='''# Read-only commands bypass the legacy script/config initialization.
case "${1:-}" in
 --runtime-status) exec "$MODDIR/bin/resusfs-control" status;;
 --force-update) exec "$MODDIR/bin/resusfs-control" status;;
 --runtime-set) shift;exec "$MODDIR/bin/resusfs-control" runtime-set "$@";;
 --priority-set) shift;exec "$MODDIR/bin/resusfs-control" priority-set "$@";;
 --status) "$SUSFS_BIN" show version; "$SUSFS_BIN" show variant; "$SUSFS_BIN" show enabled_features; exit;;
esac
# Both new and previously scheduled UserHub/cron commands pass this dispatcher.
# Existing script files and schedules remain untouched while execution pauses.
case "${1:-}" in
 --action|--stage-early|--stage-late|--apply-*|--run-script|--run-postfs-scripts|--run-bootcompleted-scripts|--sync-cron-scripts)
  "$MODDIR/bin/resusfs-control" allowed || exit $?;;
esac
supported_susfs_version() { case "$1" in v2.3.0|v2.4.0) return 0;; *) return 1;; esac; }
'''
 text=once(text,anchor,early+'\n'+anchor)
 text=once(text,'! version_ge "$susfs_version" "$SUSFS_MIN_VERSION"','! supported_susfs_version "$susfs_version"')
 text=once(text,'status_report() {','''status_report() {
    if ! "$MODDIR/bin/resusfs-control" allowed; then
        sed -i 's/^description=.*/description=status: paused; ReSuSFS is not the active audited SUSFS owner/' "$MODDIR/module.prop"
        return
    fi''')
 put('ReSuSFS.sh',text)
 for name,stage,anchor in [('post-fs-data.sh','runtime','sh $MODDIR/ReSuSFS.sh --run-postfs-scripts'),('boot-completed.sh','priority','sh $MODDIR/ReSuSFS.sh --run-bootcompleted-scripts')]:
  text=files[name].decode();text=once(text,anchor,f'sh "$MODDIR/bin/resusfs-control" restore {stage}\n\n'+anchor)
  if name=='post-fs-data.sh':text=once(text,'load_susfs_lkm','"$MODDIR/bin/resusfs-control" owner-allowed || exit $?\n\nload_susfs_lkm')
  put(name,text)
 text=files['utils.sh'].decode();start=text.index('update_susfs() {');end=text.index('\ncheck_susfs_support() {',start)
 text=text[:start]+'''update_susfs() {
    # Updates are reproducible source-built module releases, never global swaps.
    [ -x "$MODDIR/bin/ksu_susfs" ] || return 1
    "$MODDIR/bin/ksu_susfs" show version
}
''' +text[end:];put('utils.sh',text)
 put('action.sh','#!/system/bin/sh\nexec /data/adb/modules/ReSuSFS/bin/resusfs-control status\n')
 put('uninstall.sh','#!/system/bin/sh\n# Global CLI, shared adapters and persistent profiles belong to their owners.\n# KernelSU removes this module directory; no external files are deleted.\nexit 0\n')
 html=files['webroot/index.html'].decode();html=once(html,'</head>','  <link rel="stylesheet" href="./assets/resusfs-runtime.css">\n  <script type="module" src="./assets/resusfs-runtime.mjs"></script>\n</head>');put('webroot/index.html',html)
 for name in ('resusfs-runtime.mjs','resusfs-runtime.css'):put('webroot/assets/'+name,(HERE/name).read_bytes())
 put('README-KAOSLAB-SUSFS240.md',(HERE/'README.md').read_bytes())
 put('SUSFS-TOOL-BUILD.json',json.dumps(build,indent=2)+'\n')
 if (HERE/'DEVICE-READ-VERIFICATION.json').exists():put('LOCAL-DEVICE-READ-VERIFICATION.json',(HERE/'DEVICE-READ-VERIFICATION.json').read_bytes())
 for name in source['source_files_sha256']:put('source/ksu_susfs/'+name,(HERE/'upstream'/name).read_bytes())
 unchanged={name:sha(data) for name,data in original.items() if files.get(name)==data}
 changed={name:sha(data) for name,data in files.items() if original.get(name)!=data}
 manifest={'schema':1,'module_id':'ReSuSFS','baseline_sha256':base['sha256'],'official_release':base['official_release'],'susfs_version':'v2.4.0','supported_kernel_versions':['v2.3.0','v2.4.0'],'susfs_source_pin':source['pin'],'susfs_tool_sha256':sha(tool),'runtime_helper_sha256':sha(runtime),'new_settings_default_enabled':False,'existing_config_overwritten':False,'owner_transferred':False,'global_cli_replaced':False,'unchanged_files_sha256':unchanged,'changed_files_sha256':changed,'device_installation_tested':False}
 put('build-manifest.json',json.dumps(manifest,indent=2)+'\n')
 put('SHA256SUMS',''.join(sha(data)+'  '+name+'\n' for name,data in sorted(files.items())))
 output.mkdir(parents=True,exist_ok=True);target=output/NAME
 with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
  for name,data in sorted(files.items()):
   info=zipfile.ZipInfo(name,(2026,11,8,0,0,0));info.create_system=3;info.external_attr=((0o100755 if name.startswith('bin/') or name.endswith('.sh') or name.endswith('update-binary') else 0o100644)<<16);info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,data)
 with zipfile.ZipFile(target) as z:
  if z.testzip() is not None:raise RuntimeError('Final ZIP CRC failure')
  for line in z.read('SHA256SUMS').decode().splitlines():
   digest,name=line.split('  ',1)
   if sha(z.read(name))!=digest:raise RuntimeError('Final ZIP digest failure: '+name)
 result=dict(manifest,zip_name=NAME,zip_sha256=sha(target.read_bytes()),bytes=target.stat().st_size,crc_and_all_member_checksums_passed=True)
 (output/'PACKAGE-VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n');(output/'SHA256SUMS').write_text(result['zip_sha256']+'  '+NAME+'\n')
 print(json.dumps({k:v for k,v in result.items() if not isinstance(v,dict)},indent=2));return result
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime-helper',type=Path,required=True);p.add_argument('--susfs-tool',type=Path,default=HERE/'bin/ksu_susfs');p.add_argument('--output',type=Path,required=True);a=p.parse_args();package(a.runtime_helper,a.susfs_tool,a.output)
