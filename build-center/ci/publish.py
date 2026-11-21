"""Publish actual flash ZIPs only after all required build jobs have succeeded."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import shutil
import sys
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from center_core import request, checked_file


def checked_guard6(path,plan):
    required_hooks={'bin/zm-susfs-owner','bin/zm-patch-policy','bin/zm-bootguard','bin/zm-droidspaces-vfs','bin/zm-open-redirect','post-fs-data.sh','boot-completed.sh','service.sh'}
    required_pages={'webroot/index.html','webroot/susfs-rules.html','webroot/brene75.html','webroot/brene69.html','webroot/susfs-brene.html'}
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)) or archive.testzip() is not None:
            raise RuntimeError('Guard6 archive integrity failed')
        if not (required_hooks|required_pages) <= set(names):
            raise RuntimeError('Complete Guard6/BRENE controls are missing')
        if any(n in {'webroot/cache.json','webroot/zm-init.js'} or n.startswith('.vfs-stage/') for n in names):
            raise RuntimeError('Guard6 contains device runtime state')
        manifest=json.loads(archive.read('build-manifest.json'))
        for key,expected in [('sukisu_version',plan['sukisu_code']),('sukisu_pin',plan['sukisu_commit']),('susfs_version',plan['susfs_version']),('susfs_source_pin',plan['susfs_commit'])]:
            if manifest.get(key)!=expected:raise RuntimeError('Guard6 source pair mismatch: '+key)
        for key in ('original_controls_preserved','runtime_menu_additive','configuration_preserved'):
            if manifest.get(key) is not True:raise RuntimeError('Guard6 preservation requirement failed: '+key)
        preserved=manifest.get('baseline_files_preserved_sha256',{})
        if not required_hooks <= preserved.keys():raise RuntimeError('Guard6 preserved backend evidence missing')
        for name,digest in preserved.items():
            if hashlib.sha256(archive.read(name)).hexdigest()!=digest:raise RuntimeError('Guard6 preserved file changed: '+name)
        helper=archive.read('bin/susfs-runtime')
        if helper[:6]!=b'\x7fELF\x02\x01' or helper[18:20]!=b'\xb7\x00':
            raise RuntimeError('Guard6 runtime helper is not AArch64 ELF')
        if hashlib.sha256(helper).hexdigest()!=manifest['runtime_helper_sha256']:
            raise RuntimeError('Guard6 runtime helper digest mismatch')
        checked=set()
        for line in archive.read('SHA256SUMS').decode().splitlines():
            digest,name=line.split('  ',1)
            if name in checked or hashlib.sha256(archive.read(name)).hexdigest()!=digest:
                raise RuntimeError('Guard6 member checksum failed: '+name)
            checked.add(name)
        if set(names)-{'SHA256SUMS','COMPAT-SHA256SUMS'} != checked:
            raise RuntimeError('Guard6 member checksum coverage incomplete')
    return manifest


def matching_susfs_tool(directory,plan):
    binary=directory/'ksu_susfs'
    receipt=directory/'SUSFS-TOOL-BUILD.json'
    proof=json.loads(receipt.read_text())
    payload=binary.read_bytes()
    if (proof.get('pin')!=plan['susfs_commit'] or proof.get('susfs_version')!=plan['susfs_version']
            or proof.get('built_from_official_c_sources') is not True
            or proof.get('target')!='aarch64-linux-android26'
            or proof.get('sha256')!=hashlib.sha256(payload).hexdigest()
            or proof.get('bytes')!=len(payload)
            or payload[:6]!=b'\x7fELF\x02\x01' or payload[18:20]!=b'\xb7\x00'):
        raise RuntimeError('SuSFS ARM64 tool and source receipt do not match')
    return binary,receipt


def collect_companions(root,plan,module_artifacts=Path('resusfs-files'),guard_artifacts=Path('guard6-files')):
    if plan['susfs_version']!='v2.4.0':
        binary,receipt=matching_susfs_tool(module_artifacts,plan)
        target=root/f"SuSFS-{plan['susfs_version']}-{plan['susfs_commit'][:8]}-ARM64-CLI.zip"
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(binary,binary.name)
            archive.write(receipt,receipt.name)
        return {'susfs_cli_filename':target.name,'susfs_cli_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
                'companion_compatibility':'SuSFS version outside the supported ReSuSFS and Guard6.13 module ABI'}

    modules=list(module_artifacts.rglob('ReSuSFS-*.zip'))
    if len(modules)!=1:raise RuntimeError('Expected exactly one matching ReSuSFS module')
    with zipfile.ZipFile(modules[0]) as archive:
        manifest=json.loads(archive.read('build-manifest.json'))
        if manifest['susfs_source_pin']!=plan['susfs_commit'] or manifest['susfs_version']!=plan['susfs_version']:
            raise RuntimeError('ReSuSFS source pair does not match the kernel')
    guards=list(guard_artifacts.rglob('ZeroMount-Guard6.13-BRENE75-*.zip'))
    if len(guards)!=1:raise RuntimeError('Expected exactly one complete matching Guard6.13/BRENE75 module')
    checked_guard6(guards[0],plan)
    for archive in (modules[0],guards[0]):
        shutil.copyfile(archive,root/archive.name)
    return {'guard6_filename':guards[0].name,'guard6_sha256':hashlib.sha256(guards[0].read_bytes()).hexdigest(),
            'guard6_original_controls_preserved':True,'guard6_runtime_menu_additive':True}


def main():
    root=Path(sys.argv[1]);plan=json.loads(os.environ['CENTER_PLAN']);token=os.environ['GH_TOKEN']
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
        runtime=json.loads(z.read('SUSFS-RUNTIME.json'))
        susfs_release=json.loads(z.read('SUSFS-RELEASE240.json'))
        firmware=json.loads(z.read('FIRMWARE-TARGET.json'))
        image_sha256=hashlib.sha256(z.read('Image')).hexdigest()
        if firmware['firmware']!=plan['firmware'] or firmware['profile']!=plan['profile'] or firmware['image_sha256']!=image_sha256:
            raise RuntimeError('Measured firmware target does not match the packaged Image')
        if hidden['revision']!=plan.get('kernel_revision') or hidden['image_sha256']!=image_sha256:
            raise RuntimeError('Hidden-name correction does not match the packaged Image')
        if (runtime.get('image_sha256')!=image_sha256 or runtime.get('susfs_release')!=susfs_release
                or susfs_release.get('upstream_release_pin')!=plan['susfs_commit']
                or susfs_release.get('susfs_version')!=plan['susfs_version']):
            raise RuntimeError('Packaged Image does not attest the pinned SuSFS release')
    companions=collect_companions(root,plan)
    source=request(plan['susfs_source_url'],binary=True)
    source_name=f"SuSFS-{plan['susfs_version']}-{plan['susfs_commit'][:8]}-sources.zip"
    (root/source_name).write_bytes(source)
    if plan.get('manager'):
        a=plan['manager'];raw=request(a['browser_download_url'],binary=True)
        raw,name,_=checked_file(raw,a['name'],a.get('digest',''),'apk');(root/name).write_bytes(raw)
    plan.update(ci_full_kernel_build='passed',ci_strict_kmi_crc='passed',device_boot_tested=False,
                kernel_filename=kernel.name,kernel_sha256=hashlib.sha256(kernel.read_bytes()).hexdigest(),**companions)
    (root/'build-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    notes=root/'RELEASE-NOTES.md'
    notes.write_text(f"SukiSU {plan['sukisu_code']} + SuSFS {plan['susfs_version']}\n\n"
        f"S928BXXU6EZJB / EUX / Linux 6.1.162.\n\n"
        f"SukiSU commit: {plan['sukisu_commit']}\n\nSuSFS commit: {plan['susfs_commit']}\n\n"
        + (f"Requested source: official PR merge preview, {plan['sukisu_pull_request']}. This is a preview, not the main-branch version.\n\n" if plan.get('sukisu_source_kind') == 'official-pull-request-merge-preview' else '') +
        f"Kernel, ARM64 userspace and ZeroMount compatibility jobs passed. Samsung Strict KMI and DLKM CRC gates passed.\n\n"
        + ("The separate Guard6.13/BRENE75 ZIP retains the complete custom module and original controls, with Runtime added to the existing menu. The matching ReSuSFS module contains the source-built official tool.\n\n"
           if 'guard6_filename' in companions else
           "The ARM64 CLI ZIP contains the official tool built from this SuSFS commit. The custom ReSuSFS and Guard6.13 packages still require their audited SuSFS 2.4.0 interface.\n\n") +
        f"CI run: https://github.com/{plan['repository']}/actions/runs/{plan['run_id']}\n\n"
        f"Kernel correction: {plan['kernel_revision']}. Native and compat directory callbacks apply the existing runtime/owner-aware HIDDEN_NAME policy. Exact-C regression and packaged Image receipts are included.\n\n"
        "The AnyKernel3 ZIP contains the kernel with integrated SuSFS. The separate source ZIP contains the exact SuSFS sources. Device boot and installation were not tested by CI.\n",encoding='utf-8')
    sums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(root.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt')
    (root/'SHA256SUMS.txt').write_text(sums,encoding='utf-8')
    # gh obtains the Actions token from GH_TOKEN, never from a command argument.
    subprocess.run(['gh','release','create',plan['release_tag'],'--repo',plan['repository'],
                    '--target',os.environ['GITHUB_SHA'],'--prerelease','--title',
                    f"S928B EZJB · SukiSU {plan['sukisu_code']} · SuSFS {plan['susfs_version']}",
                    '--notes-file',str(notes),*[str(p) for p in root.iterdir() if p.is_file()]],check=True)


if __name__=='__main__':main()
