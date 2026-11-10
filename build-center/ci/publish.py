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
        if 'S928BXXS6EZJ1' not in strict or 'strict' not in strict.lower():
            raise RuntimeError('Strict firmware evidence missing')
        if 'Requires firmware S928BXXS6EZJ1' not in z.read('anykernel.sh').decode():
            raise RuntimeError('Flash installer does not accept the audited EZJ1 firmware')
        hidden=json.loads(z.read('SUSFS-HIDDEN-NAME-READDIR.json'))
        firmware=json.loads(z.read('FIRMWARE-TARGET.json'))
        if firmware['firmware']!=plan['firmware'] or firmware['profile']!=plan['profile'] or firmware['image_sha256']!=hashlib.sha256(z.read('Image')).hexdigest():
            raise RuntimeError('Measured firmware target does not match the packaged Image')
        if hidden['revision']!=plan.get('kernel_revision') or hidden['image_sha256']!=hashlib.sha256(z.read('Image')).hexdigest():
            raise RuntimeError('Hidden-name correction does not match the packaged Image')
    modules=list(Path('resusfs-files').rglob('ReSuSFS-*.zip'))
    if len(modules)!=1:raise RuntimeError('Expected exactly one matching ReSuSFS module')
    with zipfile.ZipFile(modules[0]) as z:
        manifest=json.loads(z.read('build-manifest.json'))
        if manifest['susfs_source_pin']!=plan['susfs_commit'] or manifest['susfs_version']!=plan['susfs_version']:
            raise RuntimeError('ReSuSFS source pair does not match the kernel')
    shutil.copyfile(modules[0],root/modules[0].name)
    source=request(plan['susfs_source_url'],binary=True)
    source_name=f"SuSFS-{plan['susfs_version']}-{plan['susfs_commit'][:8]}-sources.zip"
    (root/source_name).write_bytes(source)
    if plan.get('manager'):
        a=plan['manager'];raw=request(a['browser_download_url'],binary=True)
        raw,name,_=checked_file(raw,a['name'],a.get('digest',''),'apk');(root/name).write_bytes(raw)
    plan.update(ci_full_kernel_build='passed',ci_strict_kmi_crc='passed',device_boot_tested=False,
                kernel_filename=kernel.name,kernel_sha256=hashlib.sha256(kernel.read_bytes()).hexdigest())
    (root/'build-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    notes=root/'RELEASE-NOTES.md'
    notes.write_text(f"SukiSU {plan['sukisu_code']} + SuSFS {plan['susfs_version']}\n\n"
        f"S928BXXS6EZJ1 / EUX / Linux 6.1.162.\n\n"
        f"SukiSU commit: {plan['sukisu_commit']}\n\nSuSFS commit: {plan['susfs_commit']}\n\n"
        f"Kernel, ARM64 userspace and ZeroMount compatibility jobs passed. Samsung Strict KMI and DLKM CRC gates passed.\n\n"
        f"CI run: https://github.com/{plan['repository']}/actions/runs/{plan['run_id']}\n\n"
        f"Kernel correction: {plan['kernel_revision']}. Native and compat directory callbacks apply the existing runtime/owner-aware HIDDEN_NAME policy. Exact-C regression and packaged Image receipts are included.\n\n"
        "The kernel ZIP is the actual AnyKernel3 flash package. SuSFS is integrated into this kernel. The ReSuSFS module contains the matching source-built official tool and retained module settings; the separate source ZIP is a source archive. Device boot and installation were not tested by CI.\n",encoding='utf-8')
    sums=''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n' for p in sorted(root.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt')
    (root/'SHA256SUMS.txt').write_text(sums,encoding='utf-8')
    # gh obtains the Actions token from GH_TOKEN, never from a command argument.
    subprocess.run(['gh','release','create',plan['release_tag'],'--repo',plan['repository'],
                    '--target',os.environ['GITHUB_SHA'],'--prerelease','--title',
                    f"S928B EZJ1 · SukiSU {plan['sukisu_code']} · SuSFS {plan['susfs_version']}",
                    '--notes-file',str(notes),*[str(p) for p in root.iterdir() if p.is_file()]],check=True)


if __name__=='__main__':main()
