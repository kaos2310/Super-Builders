"""Live CI integration, source capture and three-way official SuSFS updates."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent


def context():
    root = next((p for p in (HERE, *HERE.parents) if (p/'.build-center-plan.json').exists()), None)
    if root is None:
        raise RuntimeError('No immutable Build Center plan')
    return root, json.loads((root/'.build-center-plan.json').read_text())


def command(*args, input=None, cwd=None):
    p = subprocess.run(list(map(str, args)), input=input, capture_output=True, cwd=cwd)
    if p.returncode:
        raise RuntimeError('Command failed: '+str(args[0])+'\n'+p.stderr.decode(errors='replace')[-2500:])
    return p.stdout


def digest(data): return hashlib.sha256(data).hexdigest()


def native(common, ksu, pin):
    if command('git','-C',ksu,'rev-parse','HEAD').decode().strip() != pin:
        raise RuntimeError('Source pin mismatch')
    path='kernel/feature/selinux_hide.c'
    if (ksu/path).read_bytes() != command('git','-C',ksu,'show',pin+':'+path):
        raise RuntimeError('Native SukiSU SELinux implementation changed')
    for name in ('security/selinux/hooks.c','security/selinux/selinuxfs.c'):
        if any(t in (common/name).read_text() for t in ('fake_state','ksu_selinux_hide_running','my_setprocattr','my_sel_open_handle_status')):
            raise RuntimeError('Parallel SELinux hook: '+name)
    if 'susfs_is_avc_log_spoofing_enabled' not in (common/'security/selinux/avc.c').read_text():
        raise RuntimeError('SuSFS AVC logging lost')


def port_apply():
    p=argparse.ArgumentParser()
    for name in ('common','ksu','patch'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--evidence',type=Path);a=p.parse_args()
    root,plan=context();code=plan['sukisu_code'];helper=root/'android14-6.1/build-helpers'
    port=helper/f'sukisu-{code}-susfs'
    if command('git','-C',a.ksu,'rev-parse','HEAD').decode().strip()!=plan['sukisu_commit']:
        raise RuntimeError('Exact planned source required')
    if int(command('git','-C',a.ksu,'rev-list','--count','HEAD'))!=plan['sukisu_count']:
        raise RuntimeError('Full source history/version mismatch')
    make=(a.common/'Makefile').read_text()
    if not all(re.search('^'+k+' = '+v+'$',make,re.M) for k,v in [('VERSION','6'),('PATCHLEVEL','1'),('SUBLEVEL','162')]):
        raise RuntimeError('Only Linux 6.1.162 is supported')
    patch=a.patch.read_bytes()
    parts=re.split(r'(?=^diff --git )',patch.decode(),flags=re.M)
    selected=[c for c in parts if c.startswith(('diff --git a/security/selinux/hooks.c ','diff --git a/security/selinux/selinuxfs.c '))]
    if len(selected)!=2:raise RuntimeError('Expected two legacy manual SELinux sections')
    reverse=''.join(selected).encode();compat=(port/'compat.patch').read_bytes()
    command('git','-C',a.ksu,'apply','--check','-',input=compat)
    command('git','-C',a.common,'apply','--reverse','--check','-',input=reverse)
    command('git','-C',a.ksu,'apply','-',input=compat)
    command('git','-C',a.common,'apply','--reverse','-',input=reverse)
    command(sys.executable,helper/f'configure-sukisu-{code}.py',a.ksu)
    native(a.common,a.ksu,plan['sukisu_commit'])
    receipt={'schema':1,'pin':plan['sukisu_commit'],'susfs_target':plan['susfs_commit'],
             'kernel_patch_sha256':digest(patch),'compat_patch_sha256':digest(compat),
             'stage':'source_preparation','historical_evidence_reused':False,'device_runtime_tested':False}
    (a.common/f'.sukisu-{code}-susfs-port.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('Prepared native port. This is source preparation, not a compilation receipt.')


def module(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def source_hashes(ksu,common,helper,code,normalize):
    names=command('git','-C',ksu,'ls-tree','-r','--name-only','HEAD','--','kernel','uapi').decode().splitlines()
    names+=['kernel/compat/kernel_compat.h']
    runtime=None
    if normalize and (common/'.susfs-runtime-v1.json').exists():
        runtime=module(helper/f'susfs-runtime-{code}/apply.py','runtime_normalize').verify(common,ksu)
    hashes={}
    for n in names:
        p=ksu/n;data=p.readlink().as_posix().encode() if p.is_symlink() else p.read_bytes()
        if runtime and n=='kernel/supercall/dispatch.c':data=runtime['candidate/'+n].encode()
        hashes[n]=digest(data)
    return hashes


def check(common,ksu,config=None,final_capture=False):
    root,plan=context();code=plan['sukisu_code'];h=root/'android14-6.1/build-helpers'
    native(common,ksu,plan['sukisu_commit'])
    command(sys.executable,h/f'configure-sukisu-{code}.py',ksu,'--verify-only')
    command(sys.executable,h/f'susfs-priority-uid-{code}/apply.py','--common',common,'--ksu',ksu,'--verify-only')
    receipt_path=common/'.build-center-source-manifest.json'
    previous=json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    normalize=not final_capture and not (previous and previous.get('final_sources'))
    hashes=source_hashes(ksu,common,h,code,normalize)
    if previous and not final_capture and previous['sources_sha256']!=hashes:
        raise RuntimeError('Effective kernel/UAPI sources changed after capture')
    result={'schema':1,'pin':plan['sukisu_commit'],'susfs_target':plan['susfs_commit'],
            'stage':'source_manifest','final_sources':bool(final_capture or (previous and previous.get('final_sources'))),
            'sources_sha256':hashes,'device_runtime_tested':False,
            'scope':'Source identity captured in this CI run. Compilation and CRC evidence are separate subsequent gates.'}
    hidden_receipt=common/'.susfs-hidden-name-readdir.json'
    if final_capture or hidden_receipt.exists():
        hidden=module(h/'susfs-hidden-name-readdir/apply.py','hidden_name_check').verify(common)
        result['hidden_name_readdir_revision']=hidden['revision']
        result['hidden_name_sources_sha256']=hidden['output_sha256']
    receipt_path.write_text(json.dumps(result,indent=2)+'\n')
    if config:
        command(sys.executable,h/f'audit-susfs-{code}.py','--common',common,'--ksu',ksu,'--config',config)
        lines=config.read_text().splitlines()
        for item in ('CONFIG_KSU=y','CONFIG_KSU_SUSFS=y','CONFIG_KPM=y','CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER=y'):
            if item not in lines:raise RuntimeError('Missing '+item)
        if any(s in lines for s in ('CONFIG_CGROUP_PIDS=y','CONFIG_CFS_BANDWIDTH=y','CONFIG_KSU=m')):
            raise RuntimeError('Samsung profile drift')
    (h/f'sukisu-{code}-susfs/PREFLIGHT.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: current CI source identity, native SELinux and Samsung profile')


def port_check():
    p=argparse.ArgumentParser();p.add_argument('--common',type=Path,required=True);p.add_argument('--ksu',type=Path,required=True);p.add_argument('--config',type=Path)
    a=p.parse_args();check(a.common,a.ksu,a.config)


def safe_relative(name):
    path=PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or not name:
        raise RuntimeError('Unsafe upstream patch path')
    return path


def three_way(local,base,target):
    if local==base or local==target:return target
    if base==target:return local
    if base is None or target is None or local is None:
        raise RuntimeError('Conflicting upstream file creation/deletion')
    if any(b'\0' in data for data in (local,base,target)):
        raise RuntimeError('Binary merge requires review')
    with tempfile.TemporaryDirectory(prefix='susfs-merge-') as tmp:
        paths=[Path(tmp)/n for n in ('local','base','target')]
        for p,data in zip(paths,(local,base,target)):p.write_bytes(data)
        p=subprocess.run(['git','merge-file','-p',*map(str,paths)],capture_output=True)
        if p.returncode:raise RuntimeError('SuSFS-Konflikt: lokale Anpassung und Upstream ändern dieselbe Stelle.')
        return p.stdout


def prepare_susfs(common):
    root,plan=context();work=root/'.build-center-susfs';work.mkdir(exist_ok=False)
    repo=work/'upstream';command('git','init','-q',repo)
    command('git','-C',repo,'remote','add','origin','https://gitlab.com/simonpunk/susfs4ksu.git')
    for pin in (plan['susfs_release_base'],plan['susfs_commit']):
        command('git','-C',repo,'fetch','--depth=1','origin',pin)
    def get(pin,path):
        p=subprocess.run(['git','-C',str(repo),'show',pin+':'+path],capture_output=True)
        return p.stdout if p.returncode==0 else None
    old,new=plan['susfs_release_base'],plan['susfs_commit']
    changed=command('git','-C',repo,'diff','--name-only',old,new,'--','kernel_patches').decode().splitlines()
    records={}
    patch_name='kernel_patches/50_add_susfs_in_gki-android14-6.1.patch'
    if patch_name in changed:
        patches=[get(old,patch_name),get(new,patch_name)]
        if any(p is None for p in patches):raise RuntimeError('Upstream GKI patch was removed')
        touched=set()
        for patch in patches:
            for n in re.findall(rb'^(?:--- a/|\+\+\+ b/)([^\r\n]+)',patch,re.M):touched.add(str(safe_relative(n.decode())))
        trees=[work/'old-patched',work/'new-patched']
        for tree,patch in zip(trees,patches):
            tree.mkdir();command('git','init','-q',tree)
            for name in touched:
                original=common/name
                if original.is_file():
                    dest=tree/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,dest)
            command('git','-C',tree,'apply','--check','-',input=patch)
            command('git','-C',tree,'apply','-',input=patch)
        for name in touched:
            records[name]=[(tree/name).read_bytes() if (tree/name).exists() else None for tree in trees]
    for name in changed:
        if name.startswith(('kernel_patches/fs/','kernel_patches/include/linux/')):
            mapped=name.removeprefix('kernel_patches/');safe_relative(mapped)
            records[mapped]=[get(old,name),get(new,name)]
    serial={}
    for number,(name,(base,target)) in enumerate(sorted(records.items())):
        if base==target:continue
        item={'base':None,'target':None}
        for kind,data in (('base',base),('target',target)):
            if data is not None:
                file=f'{number}-{kind}';(work/file).write_bytes(data);item[kind]=file
        serial[name]=item
    (work/'delta.json').write_text(json.dumps(serial,indent=2)+'\n')
    (work/'upstream-changes.json').write_text(json.dumps({'old':old,'new':new,'all_changed_files':changed,'effective_files':list(serial)},indent=2)+'\n')
    print('Official SuSFS delta:',len(serial),'effective kernel files;',len(changed),'upstream files')


def sync_susfs(common,ksu):
    root,plan=context();work=root/'.build-center-susfs';records=json.loads((work/'delta.json').read_text())
    results={}
    for name,item in records.items():
        safe_relative(name);p=common/name
        values=[(work/item[k]).read_bytes() if item[k] is not None else None for k in ('base','target')]
        results[name]=three_way(p.read_bytes() if p.exists() else None,*values)
    # All merges must succeed before any effective kernel source is changed.
    for name,data in results.items():
        p=common/name
        if data is None:
            if p.exists():p.unlink()
        else:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    header=(common/'include/linux/susfs.h').read_text()
    if not re.search(r'^#define\s+SUSFS_VERSION\s+"'+re.escape(plan['susfs_version'])+'"',header,re.M):
        raise RuntimeError('Merged SuSFS version does not match pinned upstream')
    native(common,ksu,plan['sukisu_commit'])
    receipt={'source_pin':plan['susfs_commit'],'release_base':plan['susfs_release_base'],
             'susfs_version':plan['susfs_version'],'updated_files':list(results),'conflicts':0}
    (common/'.build-center-susfs-update.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('PASS: official SuSFS delta merged without conflicts')


def update_tool():
    root,plan=context()
    if plan['susfs_version']!='v2.4.0':
        raise RuntimeError('ReSuSFS adapter requires a reviewed compatibility update for '+plan['susfs_version'])
    h=root/f"android14-6.1/build-helpers/resusfs-{plan['sukisu_code']}-240"
    repo=root/'.build-center-susfs-tool'
    if not (repo/'.git').exists():
        command('git','init','-q',repo)
        command('git','-C',repo,'remote','add','origin','https://gitlab.com/simonpunk/susfs4ksu.git')
    elif command('git','-C',repo,'remote','get-url','origin').decode().strip()!='https://gitlab.com/simonpunk/susfs4ksu.git':
        raise RuntimeError('Unexpected existing SuSFS tool source remote')
    command('git','-C',repo,'fetch','--depth=1','origin',plan['susfs_commit'])
    names=command('git','-C',repo,'ls-tree','-r','--name-only',plan['susfs_commit'],'--','ksu_susfs/jni').decode().splitlines()
    files={}
    for name in names:
        short=name.removeprefix('ksu_susfs/jni/');safe_relative(short)
        files[short]=command('git','-C',repo,'show',plan['susfs_commit']+':'+name)
    files['LICENSE']=command('git','-C',repo,'show',plan['susfs_commit']+':LICENSE')
    if not {'main.c','includes/susfs_defs.h'}<=files.keys():raise RuntimeError('Official SuSFS CLI layout changed')
    dest=h/'upstream'
    for p in dest.rglob('*'):
        if p.is_file() and p.relative_to(dest).as_posix() not in files:p.unlink()
    for name,data in files.items():
        p=dest/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    source={'repository':'https://gitlab.com/simonpunk/susfs4ksu','branch':'gki-android14-6.1',
        'pin':plan['susfs_commit'],'source_files_sha256':{n:digest(data) for n,data in files.items()},
        'native_binary_is_source_build':True,'device_tested':False}
    (h/'SOURCE.json').write_text(json.dumps(source,indent=2)+'\n')
    test=h/'test.py'
    original=test.read_text()
    fixed=original.replace("self.assertEqual(source['pin'],'a2165b6f875b73e2f87d3c6f12814efac8de061d')",
        "self.assertEqual(source['pin'],json.loads((HERE.parents[2]/'.build-center-plan.json').read_text())['susfs_commit'])")
    test.write_text(fixed,encoding='utf-8',newline='\n')
    print('Official SuSFS CLI refreshed at',plan['susfs_commit'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('susfs-before','susfs-after','capture-final','update-tool'));p.add_argument('--common',type=Path);p.add_argument('--ksu',type=Path)
    a=p.parse_args()
    if a.mode=='update-tool':update_tool()
    elif a.common is None:p.error('--common is required for kernel operations')
    elif a.mode=='susfs-before':prepare_susfs(a.common)
    elif a.mode=='susfs-after':sync_susfs(a.common,a.ksu)
    else:check(a.common,a.ksu,final_capture=True)
