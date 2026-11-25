"""Publish actual flash ZIPs only after all required build jobs have succeeded."""
from pathlib import Path, PurePosixPath
import hashlib
import json
import re
import os
import subprocess
import shutil
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from center_core import request, checked_file
from ci.versions import official_nova_repository


# Exact reviewed input identities; refreshed source pins require a new review.
REVIEWED_SUSFS_PIN='f76b81f2a6bf98e4029cc0c823c054edbec29803'
REVIEWED_GUARD_HOOKS={'bin/zm-bootguard': '8d8a263beacf733facf2113ebc90d80d0a3d3b419cf2c5e5087b0056a6ee0224',
 'bin/zm-droidspaces-vfs': 'b10187e796137f2dcbc9c96289eac487d5c1341276a638a086e49271331ec169',
 'bin/zm-open-redirect': 'dc70359e8574e44ab86fedb75482025ac713479aedebcb08e0a2bfd693d68d54',
 'bin/zm-patch-policy': '43cadaf09dcb7c870443ab7b27c96201c3693567e2b45f4b17bdaf76e76c8375',
 'bin/zm-susfs-owner': '6ebd7540f3957c0fd579926ad3e6ae54c129442dce2dbb7bdad949abdf26fb62',
 'boot-completed.sh': '7eb13282f1ebdae2007963c31f9b3bc9598c5948400b2bff956d42f5d57c1762',
 'post-fs-data.sh': '6ff4e732f8635fd8f9048bea3d02ef6272ca163bd5938bb83193cee0d08861ca',
 'service.sh': 'c9ded915d4424b664a56cf74993d71bb25055f552cebe6ac3341cd69d56b184c'}
REVIEWED_RESUSFS_UI={'webroot/assets/index-BujESnSu.css': '48a95e28764a4b75fc8932fee19e151a75940b7adb33df724d0f109393e3a1b2',
 'webroot/assets/index-BzLLhKnx.js': 'cfa8f42c9d2dd32a2905a20041c4213cd2df76b80fada7fe62389f175a4fa7c9'}
REVIEWED_RESUSFS_CONTROLS={'bin/resusfs-control': '0c5f9d728ed2a7a8c97c463696e9bb0c6d089850c71555b41edf4bb8455dfb03',
 'bin/resusfs-susfs': '0535b5f7d019a7d96a939dd9027c4f7f21df90b9eac0b1dfa9dd69a1ca81db12',
 'webroot/assets/resusfs-runtime.css': '70d6c8e6ece2f5a9cc527a828f56669a9246dcd40aeb1805a655eaaed55a6997',
 'webroot/assets/resusfs-runtime.mjs': '81a8d85dbcf9107a04ee86ee4f9274bbb421033655ce4d57e70eaf02f87555c6'}
REVIEWED_SUSFS_SOURCES={'Android.mk': '14b726b424787e46bc60c59c9c9b51282fe248a1bfd58ec91fdd6261f8958013',
 'Application.mk': 'a25a74b525bcd7a9bca126fe8619f4fdd75790630c514199a9224ab1a740590a',
 'LICENSE': '3da27bc7c6a063f498b4278372d48e113453f93aecc709f44276e278fc0cac12',
 'features.h': 'a6836752d37293de2d4213f5e63dc3585cb385403fa44d4f27e6b0ceb34d5c79',
 'features/avc_log_spoofing.c': '7dabf0a21f3b8f2f3dbf4d1767d5a9305ba5feb0ab372ad6d4043c7a1d0f473b',
 'features/avc_log_spoofing.h': 'c70ba14029d19f04ab08b3e987cc7c29a56392e50fa3c2ab0f851a5889d28e2f',
 'features/enable_log.c': '016c3017c219ede4fc1863f54c1d1d20ce1ab8ba9cac1b95c594ccc16b22a96c',
 'features/enable_log.h': 'fecea25709f76c75db69453c12d0a80bf184d1fa9c849fe704d4b5b14cb84ad9',
 'features/open_redirect.c': 'd63ee209cad81650b6dd8fbc63e0406d246b0c80fdbf0363ab9172ad9b57ac2a',
 'features/open_redirect.h': 'c56eed073e4cffbd84c893d79443d89a2640c94abe77080b2528c8e54cd45f18',
 'features/priority_uid_filter.c': 'eb7a42dd5de526505064d82b5d60f4977fac2554d8bdac9ae14ab07ef9bccfb9',
 'features/priority_uid_filter.h': '0d0ea046ffffee1a23832fee5c5ea90b8f9b8d8adc90fabc9fa95f7a27676df0',
 'features/show.c': '3b671db2a0fb2cd4b8093df6312f6bb99665ef90f2ea51575acb1a583b1a234e',
 'features/show.h': 'b805b8a3a58a3ce918036e78de083fbb9d33a929a4995bbc74de8a505378ab42',
 'features/spoof_cmdline_or_bootconfig.c': '8faec7780a399afa51b64e2266446e7b96f24bb4ddbe808fd6d2025224307d2e',
 'features/spoof_cmdline_or_bootconfig.h': '233a7d86a84eee55afd7acceb96aa6c8ed27fa87abe82149751d93a82a00e35e',
 'features/spoof_uname.c': '1f221f83c6df17eab286fe0bfc78ebc0276407824e3a9945a73441045519d05d',
 'features/spoof_uname.h': '0b11586bb66b2796ecfdd4889b7982a06476ba791a105a6aefba1c33f293e343',
 'features/sus_kstat.c': 'b08830b58e09a7ddc11c29b5630e1635a5447cdc1d653ce751e7277ea5b45ce4',
 'features/sus_kstat.h': '9d8ae7253be8b3e660ed731666a11289e68288cfccf887284682b115b88ad1ce',
 'features/sus_map.c': '63de418f38998e400af572da1aa5c4994e5d99428bbce40fe51ffacfc21d5cb2',
 'features/sus_map.h': 'b937696d19c88458578d3dc02817ab1269912b66501498f2c1084fa868495d3e',
 'features/sus_mount.c': '46eab0b93082a2d1e38c2d0d4591bca80cc5f25b8dc3781e568b95da78655b32',
 'features/sus_mount.h': '09225f0962f6485a6ef1d1b003cac0e6d59e0a5039573b3794d90f0dd0d85d99',
 'features/sus_path.c': 'b409f8ddfe30dbe6a4d3960d24efc8b514fabb64e3d09333be5f6105454bacae',
 'features/sus_path.h': '2a747ec08260897bbb0a4374f79d81030af89072a73ed75a5a20b6a9737a0dd2',
 'features/sus_path_uid_filter.c': 'b6e627d1ff448031e652ba6fbb1f90e482b7c5347c8472e82fe8b02ce34464ab',
 'features/sus_path_uid_filter.h': 'c693b8d1e28916e9162a8ecc8595dc7dc715726b7cf7f983e95ff4b5b623757f',
 'includes/susfs_defs.h': 'b77b9d1408135d46be7ffe443c6a4363e7513f30ca74a797e46995acdb1c16d4',
 'includes/susfs_utils.h': 'a4517e6e9603bd231cb2c278c9b04625bb57c07c5cc166275c0abeb1e2536566',
 'main.c': '947e18eb6e1c631a16a732fd209ad1164d07d9851b2bc3aecb8972c943725987',
 'susfs_utils.c': '7e3c0a3d8ec8f9c6dccf417b66c6cc35ae6edab8f475ba1eb5340e15c0f74bdc'}


def _sha(data):return hashlib.sha256(data).hexdigest()

def _read(archive,name):
    try:return archive.read(name)
    except KeyError as error:raise RuntimeError('Required module member missing: '+name) from error

def _json(archive,name):
    try:value=json.loads(_read(archive,name))
    except (ValueError,UnicodeError) as error:raise RuntimeError('Invalid module JSON: '+name) from error
    if not isinstance(value,dict):raise RuntimeError('Module JSON object required: '+name)
    return value

def _safe_name(name):
    path=PurePosixPath(name)
    return bool(name) and not path.is_absolute() and '..' not in path.parts and not any(c in name for c in ('\\','\r','\n'))

def _archive_integrity(archive,excluded_checksums):
    names=archive.namelist()
    if len(names)!=len(set(names)) or any(not _safe_name(name) for name in names):
        raise RuntimeError('Module archive contains duplicate or unsafe paths')
    if any((item.external_attr>>16)&0o170000==0o120000 for item in archive.infolist()):
        raise RuntimeError('Module archive must not contain symlinks')
    if archive.testzip() is not None:raise RuntimeError('Module archive CRC integrity failed')
    checked=set()
    for line in _read(archive,'SHA256SUMS').decode().splitlines():
        fields=line.split('  ',1)
        if len(fields)!=2 or not re.fullmatch('[0-9a-f]{64}',fields[0]):
            raise RuntimeError('Invalid module checksum record')
        digest,name=fields
        if name in checked or name in excluded_checksums or _sha(_read(archive,name))!=digest:
            raise RuntimeError('Module member checksum failed: '+name)
        checked.add(name)
    if set(names)-excluded_checksums!=checked:raise RuntimeError('Module member checksum coverage incomplete')
    return set(names)

def _elf(archive,name,expected_hash):
    data=_read(archive,name)
    if len(data)<64 or data[:6]!=b'\x7fELF\x02\x01' or data[18:20]!=b'\xb7\x00':
        raise RuntimeError('Module helper is not AArch64 ELF: '+name)
    if _sha(data)!=expected_hash:raise RuntimeError('Module helper digest mismatch: '+name)
    return data

def _preserved(archive,mapping,required):
    if not isinstance(mapping,dict) or not set(required)<=mapping.keys():
        raise RuntimeError('Required preserved module evidence missing')
    for name,digest in mapping.items():
        if not _safe_name(name) or _sha(_read(archive,name))!=digest:
            raise RuntimeError('Preserved module file changed: '+name)
    for name,digest in required.items():
        if mapping[name]!=digest:raise RuntimeError('Reviewed original feature was replaced: '+name)

def _nova_identity(manifest,plan,code_key,pin_key):
    expected={'sukisu_family':'nova','sukisu_repository':plan.get('sukisu_repository'),
              'sukisu_count':plan.get('sukisu_count'),code_key:plan['sukisu_code'],pin_key:plan['sukisu_commit'],
              'susfs_version':plan['susfs_version'],'susfs_source_pin':plan['susfs_commit']}
    if plan.get('sukisu_family')!='nova' or not official_nova_repository(plan):
        raise RuntimeError('Reviewed Nova repository/family required')
    if plan.get('sukisu_repository_url'):
        expected['sukisu_repository_url']=plan['sukisu_repository_url']
    if type(plan.get('sukisu_count')) is not int or plan['sukisu_code']!=30000+plan['sukisu_count']+996:
        raise RuntimeError('Nova source/version mapping mismatch')
    for key,value in expected.items():
        if manifest.get(key)!=value:raise RuntimeError('Module Nova source pair mismatch: '+key)

def _verify_design(archive,manifest,plan,source_path,name):
    if not plan.get('module_design'):
        return
    source=Path(__file__).resolve().parents[1]/source_path
    css=source.read_bytes()
    if (manifest.get('module_design')!=plan['module_design']
            or manifest.get('module_design_sha256')!=_sha(css) or _read(archive,'webroot/assets/'+name)!=css
            or ('./assets/'+name).encode() not in _read(archive,'webroot/index.html')):
        raise RuntimeError('Matching 3D WebUI not found in module archive')

def _private_cli(archive,manifest,plan,hash_key):
    tool=_elf(archive,'bin/ksu_susfs',manifest.get(hash_key))
    proof=_json(archive,'SUSFS-TOOL-BUILD.json')
    if (plan['susfs_commit']!=REVIEWED_SUSFS_PIN or
        proof.get('pin')!=plan['susfs_commit'] or proof.get('sha256')!=_sha(tool) or
        proof.get('bytes')!=len(tool) or proof.get('target')!='aarch64-linux-android26' or
        proof.get('repository')!='https://gitlab.com/simonpunk/susfs4ksu' or
        proof.get('built_from_official_c_sources') is not True or
        proof.get('source_files_sha256')!=REVIEWED_SUSFS_SOURCES or
        proof.get('test_fixture') is True or b'set_sus_path_uid_filter' not in tool):
        raise RuntimeError('Latest private SUSFS CLI build/source proof failed')
    for name,digest in REVIEWED_SUSFS_SOURCES.items():
        if _sha(_read(archive,'source/ksu_susfs/'+name))!=digest:
            raise RuntimeError('Packaged official CLI source mismatch: '+name)
    return proof

def checked_guard6(path,plan):
    required_hooks=set(REVIEWED_GUARD_HOOKS)
    required_pages={'webroot/index.html','webroot/susfs-rules.html','webroot/brene75.html','webroot/brene69.html','webroot/susfs-brene.html'}
    with zipfile.ZipFile(path) as archive:
        names=_archive_integrity(archive,{'SHA256SUMS','COMPAT-SHA256SUMS'})
        if not (required_hooks|required_pages)<=names:raise RuntimeError('Complete Guard6/BRENE controls are missing')
        if any(n in {'webroot/cache.json','webroot/zm-init.js'} or n.startswith('.vfs-stage/') for n in names):
            raise RuntimeError('Guard6 contains device runtime state')
        manifest=_json(archive,'build-manifest.json')
        for key,expected in [('sukisu_version',plan['sukisu_code']),('sukisu_pin',plan['sukisu_commit']),('susfs_version',plan['susfs_version']),('susfs_source_pin',plan['susfs_commit'])]:
            if manifest.get(key)!=expected:raise RuntimeError('Guard6 source pair mismatch: '+key)
        for key in ('original_controls_preserved','runtime_menu_additive','configuration_preserved'):
            if manifest.get(key) is not True:raise RuntimeError('Guard6 preservation requirement failed: '+key)
        preserved=manifest.get('baseline_files_preserved_sha256',{})
        # Historical packages retain their old test contract. Nova is bound to
        # reviewed original hook hashes, not just self-reported preserved maps.
        if plan.get('sukisu_family')=='nova':
            _nova_identity(manifest,plan,'sukisu_version','sukisu_pin')
            _verify_design(archive,manifest,plan,'guard6/zm-3d.css','zm-susfs.css')
            if manifest.get('firmware')!=plan['firmware'] or manifest.get('prop_watch_native_entry')!='bin/arm64-v8a/zm-native-core':
                raise RuntimeError('Guard6 firmware or prop-watch endpoint mismatch')
            if manifest.get('brene_version')!='0.0.76' or 'webroot/brene76.html' not in names or 'bin/zm-brene76' not in names:
                raise RuntimeError('Complete BRENE76 integration missing')
            if manifest.get('private_susfs_tool_source_pin')!=plan['susfs_commit']:
                raise RuntimeError('Guard6 private tool source pair mismatch')
            _private_cli(archive,manifest,plan,'private_susfs_tool_sha256')
            _elf(archive,'bin/arm64-v8a/zm-native-core',manifest.get('native_core_sha256'))
            _preserved(archive,preserved,REVIEWED_GUARD_HOOKS)
        else:
            if not required_hooks<=preserved.keys():raise RuntimeError('Guard6 preserved backend evidence missing')
            _preserved(archive,preserved,{})
        _elf(archive,'bin/susfs-runtime',manifest.get('runtime_helper_sha256'))
    return manifest

def checked_resusfs(path,plan):
    with zipfile.ZipFile(path) as archive:
        names=_archive_integrity(archive,{'SHA256SUMS'})
        manifest=_json(archive,'build-manifest.json')
        _nova_identity(manifest,plan,'sukisu_code','sukisu_source_pin')
        _verify_design(archive,manifest,plan,'resusfs/resusfs-3d.css','resusfs-3d.css')
        if manifest.get('module_id')!='ReSuSFS' or manifest.get('revision')!='r3':
            raise RuntimeError('Matching complete ReSuSFS r3 required')
        if manifest.get('target_profile')!=plan.get('profile'):
            raise RuntimeError('ReSuSFS firmware profile mismatch')
        for key in ('original_ui_preserved','runtime_ui_is_separate_addition'):
            if manifest.get(key) is not True:raise RuntimeError('ReSuSFS original UI/Runtime preservation failed: '+key)
        for key in ('existing_config_overwritten','owner_transferred','global_cli_replaced'):
            if manifest.get(key) is not False:raise RuntimeError('ReSuSFS persistence/ownership requirement failed: '+key)
        required={'ReSuSFS.sh','bin/resusfs-control','bin/resusfs-susfs','bin/resusfs-path-filter',
                  'webroot/index.html','webroot/assets/resusfs-runtime.mjs','webroot/assets/resusfs-path-filter.mjs'}
        if not required<=names:raise RuntimeError('Complete ReSuSFS classic/additive controls missing')
        _private_cli(archive,manifest,plan,'susfs_tool_sha256')
        _elf(archive,'bin/susfs-runtime',manifest.get('runtime_helper_sha256'))
        _preserved(archive,manifest.get('unchanged_files_sha256'),REVIEWED_RESUSFS_UI)
        _preserved(archive,manifest.get('preserved_r2_files_sha256'),REVIEWED_RESUSFS_CONTROLS)
        feature=manifest.get('sus_path_uid_filter',{})
        if (not isinstance(feature,dict) or feature.get('source_pin')!=plan['susfs_commit'] or
            feature.get('command')!='set_sus_path_uid_filter' or feature.get('kernel_command_hex')!='0x55554' or
            feature.get('semantics')!='selected_app_uids_can_see_sus_path_paths' or
            feature.get('kernel_readback_available') is not False or feature.get('status_issues_mutation') is not False or
            feature.get('native_support_probed_on_read') is not False):
            raise RuntimeError('ReSuSFS native UID filter contract mismatch')
    return manifest


def main():
    root=Path(sys.argv[1]);plan=json.loads(os.environ['CENTER_PLAN'])
    artifact_only=os.environ.get('CENTER_ARTIFACT_ONLY')=='true'
    if not artifact_only and not os.environ.get('GH_TOKEN'):
        raise RuntimeError('GitHub release credentials required')
    zips=list(root.rglob('*.zip'))
    if len(zips)!=1:raise RuntimeError('Expected exactly one strict flash ZIP')
    kernel=zips[0]
    with zipfile.ZipFile(kernel) as z:
        names=set(z.namelist())
        if not {'anykernel.sh','STRICT-KMI.txt'}<=names or 'Image' not in names:
            raise RuntimeError('Strict AnyKernel3 payload missing')
        strict=z.read('STRICT-KMI.txt').decode()
        if 'S928BXXU6EZJB' not in strict or 'strict' not in strict.lower():
            raise RuntimeError('Strict firmware evidence missing')
        if 'Requires firmware S928BXXU6EZJB' not in z.read('anykernel.sh').decode():
            raise RuntimeError('Flash installer does not accept the audited EZJB firmware')
        hidden=json.loads(z.read('SUSFS-HIDDEN-NAME-READDIR.json'))
        firmware=json.loads(z.read('FIRMWARE-TARGET.json'))
        if firmware['firmware']!=plan['firmware'] or firmware['profile']!=plan['profile'] or firmware['image_sha256']!=hashlib.sha256(z.read('Image')).hexdigest():
            raise RuntimeError('Measured firmware target does not match the packaged Image')
        if hidden['revision']!=plan.get('kernel_revision') or hidden['image_sha256']!=hashlib.sha256(z.read('Image')).hexdigest():
            raise RuntimeError('Hidden-name correction does not match the packaged Image')
        runtime=_json(z,'SUSFS-RUNTIME.json')
        sus_path=runtime.get('sus_path_uid_filter', {})
        if (runtime.get('image_sha256')!=firmware['image_sha256']
                or runtime.get('pin')!=plan['sukisu_commit']
                or sus_path.get('upstream_pin')!=plan['susfs_commit']
                or sus_path.get('command')!='0x55554'
                or 'susfs_set_sus_path_uid_filter' not in sus_path.get('observed_linked_functions', [])
                or sus_path.get('semantic_host_test',{}).get('variant_exit_codes',{}).get('production')!=0):
            raise RuntimeError('Packaged Image is missing the current Nova/SUSFS filter proof')
    modules=list(Path('resusfs-files').rglob('ReSuSFS-*.zip'))
    if len(modules)!=1:raise RuntimeError('Expected exactly one matching ReSuSFS module')
    checked_resusfs(modules[0],plan)
    shutil.copyfile(modules[0],root/modules[0].name)
    guards=list(Path('guard6-files').rglob('ZeroMount-Guard6.13-BRENE76-*.zip'))
    if len(guards)!=1:raise RuntimeError('Expected exactly one complete matching Guard6.13/BRENE76 module')
    checked_guard6(guards[0],plan)
    shutil.copyfile(guards[0],root/guards[0].name)
    source=request(plan['susfs_source_url'],binary=True)
    source_name=f"SuSFS-{plan['susfs_version']}-{plan['susfs_commit'][:8]}-sources.zip"
    (root/source_name).write_bytes(source)
    if plan.get('manager'):
        a=plan['manager'];raw=request(a['browser_download_url'],binary=True)
        raw,name,_=checked_file(raw,a['name'],a.get('digest',''),'apk');(root/name).write_bytes(raw)
    plan.update(ci_full_kernel_build='passed',ci_strict_kmi_crc='passed',device_boot_tested=False,
                susfs_path_uid_filter_linked=True,
                kernel_filename=kernel.name,kernel_sha256=hashlib.sha256(kernel.read_bytes()).hexdigest(),
                resusfs_filename=modules[0].name,resusfs_sha256=hashlib.sha256(modules[0].read_bytes()).hexdigest(),
                guard6_filename=guards[0].name,guard6_sha256=hashlib.sha256(guards[0].read_bytes()).hexdigest(),
                guard6_original_controls_preserved=True,guard6_runtime_menu_additive=True)
    (root/'build-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    notes=root/'RELEASE-NOTES.md'
    notes.write_text(f"SukiSU Nova {plan['sukisu_code']} + SuSFS {plan['susfs_version']}\n\n"
        f"S928BXXU6EZJB / EUX / Linux 6.1.162.\n\n"
        f"SukiSU commit: {plan['sukisu_commit']}\n\nSuSFS commit: {plan['susfs_commit']}\n\n"
        + (f"Requested source: official PR merge preview, {plan['sukisu_pull_request']}. This is a preview, not the main-branch version.\n\n" if plan.get('sukisu_source_kind') == 'official-pull-request-merge-preview' else '') +
        f"Kernel, ARM64 userspace and ZeroMount compatibility jobs passed. Samsung Strict KMI and DLKM CRC gates passed.\n\n"
        "The separate Guard6.13/BRENE76 ZIP retains the complete custom module and original controls, with Runtime added to the existing menu. Its original configuration and ownership/boot backends are preserved and verified.\n\n"
        "ZeroMount prop-watch dispatches to the native core. CI exercises the public entry point and verifies that the former alias cannot recurse.\n\n"
        f"CI run: https://github.com/{plan['repository']}/actions/runs/{plan['run_id']}\n\n"
        f"Kernel correction: {plan['kernel_revision']}. Native and compat directory callbacks apply the existing runtime/owner-aware HIDDEN_NAME policy. Exact-C regression and packaged Image receipts are included.\n\n"
        "The kernel ZIP is the actual AnyKernel3 flash package. SuSFS is integrated into this kernel. The ReSuSFS module contains the matching source-built official tool and retained module settings; the separate source ZIP is a source archive. Device boot and installation were not tested by CI.\n",encoding='utf-8')
    sums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(root.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt')
    (root/'SHA256SUMS.txt').write_text(sums,encoding='utf-8')
    if artifact_only:
        return
    # gh obtains the Actions token from GH_TOKEN, never from a command argument.
    subprocess.run(['gh','release','create',plan['release_tag'],'--repo',plan['repository'],
                    '--target',os.environ['GITHUB_SHA'],'--prerelease','--title',
                    f"S928B EZJB · SukiSU Nova {plan['sukisu_code']} · SuSFS {plan['susfs_version']}",
                    '--notes-file',str(notes),*[str(p) for p in root.iterdir() if p.is_file()]],check=True)


if __name__=='__main__':main()
