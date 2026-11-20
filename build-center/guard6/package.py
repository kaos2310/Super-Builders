"""Package the complete audited Guard6 module with the matching Runtime addon."""
from pathlib import Path,PurePosixPath
import argparse,contextlib,hashlib,importlib.util,io,json,sys,tempfile,zipfile

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
from ci.publish import checked_guard6
from brene76.apply import apply as apply_brene76
PIN='1439545f12bffe0263690ba862139b70ee5f20cf'
SUSFS='f76b81f2a6bf98e4029cc0c823c054edbec29803'
HOOKS={'bin/zm-susfs-owner','bin/zm-patch-policy','bin/zm-bootguard','bin/zm-droidspaces-vfs','bin/zm-open-redirect','post-fs-data.sh','boot-completed.sh','service.sh'}
def sha(data):return hashlib.sha256(data).hexdigest()

def arguments():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helpers',type=Path,required=True)
    parser.add_argument('--plan',type=Path,required=True)
    parser.add_argument('--runtime-helper',type=Path,required=True)
    parser.add_argument('--susfs-tool',type=Path,required=True)
    return parser

def validate(plan,helpers):
    if (plan['sukisu_commit'],plan['sukisu_code'],plan['sukisu_count'])!=(PIN,35004,4008):
        raise RuntimeError('Guard6 requires the reviewed official SukiSU Nova35004 source')
    if plan['susfs_commit']!=SUSFS or plan['susfs_version']!='v2.4.0':
        raise RuntimeError('Guard6 requires the reviewed latest SUSFS2.4.0 source')
    if plan['profile']!='S928BXXS6EZJ1-EUX-android14-6.1.162':raise RuntimeError('Guard6 firmware profile mismatch')
    marker=helpers.parents[1]/'.build-center-plan.json'
    if json.loads(marker.read_text())!=plan:raise RuntimeError('Prepared Guard6 helpers belong to another build plan')

def package(helpers,plan,helper,output,susfs_tool):
    helpers=helpers.resolve();output=output.resolve();validate(plan,helpers)
    code=str(plan['sukisu_code'])
    baseline=helpers/f'zeromount-package-{code}'
    spec=importlib.util.spec_from_file_location('audited_guard6_package',baseline/'package.py')
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    if legacy.PIN!=PIN:raise RuntimeError('Guard6 baseline package source identity changed')
    output.mkdir(parents=True,exist_ok=True)
    base=json.loads((baseline/'BASE.json').read_text())
    with tempfile.TemporaryDirectory() as temporary:
        staged=Path(temporary)
        with contextlib.redirect_stdout(io.StringIO()):
            result=legacy.package(helper.resolve(),staged)
        with zipfile.ZipFile(staged/result['zip_name']) as archive:
            members={n:archive.read(n) for n in archive.namelist()}
    tool_source=json.loads((helpers/f'resusfs-{code}-240/SOURCE.json').read_text())
    integration=apply_brene76(members,susfs_tool.resolve(),tool_source,helpers/f'resusfs-{code}-240/upstream')
    ui=json.loads(members['UI-VERIFICATION.json'])
    changed=set(ui['changed_files_sha256'])|set(integration['changed_files_sha256'])|{'bin/arm64-v8a/zm-native-core','bin/zm','bin/zm-brene75','META-INF/com/google/android/update-binary'}
    preserved={}
    for name,digest in base['files_sha256'].items():
        if name not in changed:
            if sha(members[name])!=digest:raise RuntimeError('Original Guard6 feature file changed: '+name)
            preserved[name]=digest
    if not HOOKS<=preserved.keys():raise RuntimeError('Original Guard6 ownership/boot backend not preserved')
    settings=next(raw.decode() for n,raw in members.items() if n.startswith('webroot/assets/SettingsTab-') and n.endswith('.js'))
    for key in ('kernel_umount','sync_su_compat','try_umount','hide_nonstandard_sdcard'):
        if 'store.settings.brene.'+key not in settings:raise RuntimeError('Original Guard6 control missing: '+key)
    for name in ('webroot/susfs-rules.html','webroot/brene75.html','webroot/brene69.html'):
        if name not in members:raise RuntimeError('Original Guard6 page missing: '+name)
    members['module.prop']=('id=meta-zeromount\nname=ZeroMount\nversion=v2.0.216-dev.guard6.13.brene76.susfs240.sukisunova35004.runtime-addon1\nversionCode=2026112001\nauthor=Enginex0, KAOSLAB integration\ndescription=Guard6.13 + BRENE76 + SUSFS2.4.0; Runtime als Zusatz; SukiSU Nova35004 / S928BXXS6EZJ1 EUX.\nmetamodule=1\nbanner=banner.png\n').encode()
    for name in list(members):
        if name.startswith('README-SukiSU'):
            members[name]=members[name].replace(b'EZIF',b'EZJ1')
    manifest=json.loads(members['build-manifest.json'])
    manifest.update(schema=6,revision='guard6-nova35004-brene76-runtime-addon1',susfs_source_pin=SUSFS,susfs_release_pin=SUSFS,
        susfs_release_base=plan['susfs_release_base'],firmware='S928BXXS6EZJ1',sukisu_family='nova',brene_version='0.0.76',
        sukisu_repository=plan['sukisu_repository'],sukisu_count=plan['sukisu_count'],
        brene_upstream_archive_sha256=integration['upstream_archive_sha256'],brene_integration=integration,
        private_susfs_tool_sha256=integration['private_susfs_tool_sha256'],private_susfs_tool_source_pin=SUSFS,
        original_controls_preserved=True,runtime_menu_additive=True,configuration_preserved=True,
        baseline_files_preserved_sha256=preserved,runtime_helper_source_sha256=sha((helpers/f'susfs-runtime-{code}/susfs-runtime.c').read_bytes()),
        runtime_scope='current boot; rules and saved configuration remain unchanged',device_boot_tested=False)
    members['build-manifest.json']=(json.dumps(manifest,indent=2)+'\n').encode()
    members['README-Guard6.13-Nova35004.md']=('''# Guard6.13 / BRENE76 / SukiSU Nova35004

Vollständiges bisheriges ZeroMount-Modul für SUSFS2.4.0 und S928BXXS6EZJ1/EUX.
Ursprüngliche Regeln, BRENE75, Properties, Settings und Boot-/Ownership-Backends bleiben erhalten.
Die zusätzliche Kernel-Laufzeit-Sektion schaltet UID-Gating, Hidden-Name, Unicode und Symbol-Hiding für den aktuellen Boot.
Öffnen und Aktualisieren lesen ausschließlich Status. Änderungen benötigen die bisherigen SUSFS-/BRENE-Freigaben und einen bestätigten Runtime-ABI-v1-Status.
Ein externer SUSFS-Verwalter wird respektiert. Gespeicherte Regeln und bestehende Konfiguration werden nicht überschrieben.
Der native Guard6-Kern verwendet die bestehende exakt hashgebundene SUSFS2.4.0-Kompatibilitätsanpassung; ein Rust-Neubau wird nicht behauptet.
Runtime-Helfer wird in diesem Build aus dem passenden Quellstand neu für Android ARM64 gebaut.
Installation und Geräte-Boot dieses Pakets werden durch CI nicht geprüft.
\nSukiSU: '''+PIN+'\n\nSUSFS: '+SUSFS+'\n').encode()
    for name in ('SHA256SUMS','COMPAT-SHA256SUMS'):members.pop(name,None)
    mutable={'module.prop','customize.sh','webroot/cache.json','webroot/zm-init.js'}
    sums={n:sha(raw)+'  '+n+'\n' for n,raw in sorted(members.items())}
    members['SHA256SUMS']=''.join(sums.values()).encode()
    members['COMPAT-SHA256SUMS']=''.join(line for n,line in sums.items() if n not in mutable).encode()
    target=output/'ZeroMount-Guard6.13-BRENE76-SUSFS2.4.0-SukiSUNova35004-arm64.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
        for name,raw in sorted(members.items()):
            path=PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name:raise RuntimeError('Unsafe module member')
            info=zipfile.ZipInfo(name,(2026,11,20,0,0,0));info.create_system=3;info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100755 if name.startswith('bin/') or name.endswith(('.sh','update-binary')) else 0o100644)<<16
            archive.writestr(info,raw)
    checked_guard6(target,plan)
    result=dict(manifest,zip_name=target.name,zip_sha256=sha(target.read_bytes()),archive_crc_passed=True,all_member_checksums_passed=True)
    (output/'PACKAGE-VERIFICATION.json').write_text(json.dumps(result,indent=2)+'\n')
    (output/'SHA256SUMS').write_text(result['zip_sha256']+'  '+target.name+'\n')
    print(json.dumps({k:result[k] for k in ('zip_name','zip_sha256','sukisu_version','susfs_source_pin','original_controls_preserved','runtime_menu_additive')},indent=2))
    return result

if __name__=='__main__':
    parser=arguments();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    package(args.helpers,json.loads(args.plan.read_text()),args.runtime_helper,args.output,args.susfs_tool)
