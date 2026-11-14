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
    for name,tokens in [('security/selinux/ss/services.c',('susfs_security_context_to_sid_core','susfs_string_to_context_struct')),
                        ('fs/susfs.c',('SUS_TYPE_HLIST','susfs_mutex_lock_sus_type'))]:
        if any(token in (common/name).read_text() for token in tokens):
            raise RuntimeError('Parallel legacy SuSFS SELinux state: '+name)


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
    upstream_kbuild=command('git','-C',a.ksu,'show',plan['sukisu_commit']+':kernel/Kbuild')
    if (a.ksu/'kernel/Kbuild').read_bytes()!=upstream_kbuild:
        raise RuntimeError('Official Kbuild source changed before compatibility review')
    adapter=module(helper/'_center_kbuild_compat/kbuild_compat.py','center_kbuild_compat')
    compat=adapter.adapt_compat_patch(compat,plan,upstream_kbuild=upstream_kbuild)
    command('git','-C',a.ksu,'apply','--check','-',input=compat)
    command('git','-C',a.common,'apply','--reverse','--check','-',input=reverse)
    (port/'compat.patch').write_bytes(compat)
    command('git','-C',a.ksu,'apply','-',input=compat)
    command('git','-C',a.common,'apply','--reverse','-',input=reverse)
    command(sys.executable,helper/f'configure-sukisu-{code}.py',a.ksu)
    native(a.common,a.ksu,plan['sukisu_commit'])
    receipt={'schema':1,'pin':plan['sukisu_commit'],'susfs_target':plan['susfs_commit'],
             'kernel_patch_sha256':digest(patch),'compat_patch_sha256':digest(compat),
             'kbuild_upstream_blob':command('git','-C',a.ksu,'rev-parse',plan['sukisu_commit']+':kernel/Kbuild').decode().strip(),
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
    path_uid=wire_suspath(common,ksu,verify_only=True)
    if path_uid:result['sus_path_uid_filter']=path_uid
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


class SusfsMergeConflict(RuntimeError):
    def __init__(self,output):
        super().__init__('SuSFS-Konflikt: lokale Anpassung und Upstream ändern dieselbe Stelle.')
        self.output=output


def without_endif_annotations(data):
    # A trailing // comment on a preprocessing directive has no C semantics.
    # New upstream annotations otherwise conflict with adjacent local feature
    # blocks even when both code changes are independent.
    data=re.sub(rb'(?m)^([ \t]*#endif)[ \t]+//[ \t]*#ifdef[ \t]+CONFIG_KSU_SUSFS[A-Z0-9_]*[ \t]*(\r?)$',
                rb'\1\2',data)
    return re.sub(rb'(?m)^/\* selinux hide \*/\r?\n',b'',data)


def only_legacy_services_additions(base,target):
    added=b'''int susfs_security_context_to_sid_default(struct selinux_state *state,
\t\t\t\t    const char *scontext, u32 scontext_len,
\t\t\t\t    u32 *sid, u32 def_sid, gfp_t gfp_flags)
{
\treturn susfs_security_context_to_sid_core(state, scontext, scontext_len,
\t\t\t\t\t    sid, def_sid, gfp_flags, 1);
}

int susfs_security_context_to_sid_force(struct selinux_state *state,
\t\t\t\t  const char *scontext, u32 scontext_len,
\t\t\t\t  u32 *sid)
{
\treturn susfs_security_context_to_sid_core(state, scontext, scontext_len,
\t\t\t\t\t    sid, SECSID_NULL, GFP_KERNEL, 1);
}

'''
    return target.count(added)==1 and target.replace(added,b'').rstrip(b'\n')==base.rstrip(b'\n')


def three_way(local,base,target):
    if local==base or local==target:return target
    if base==target:return local
    if base is None or target is None or local is None:
        raise RuntimeError('Conflicting upstream file creation/deletion')
    if any(b'\0' in data for data in (local,base,target)):
        raise RuntimeError('Binary merge requires review')
    with tempfile.TemporaryDirectory(prefix='susfs-merge-') as tmp:
        paths=[Path(tmp)/n for n in ('local','base','target')]
        for p,data in zip(paths,(local,base,target)):p.write_bytes(without_endif_annotations(data))
        p=subprocess.run(['git','merge-file','-p',*map(str,paths)],capture_output=True)
        if p.returncode:raise SusfsMergeConflict(p.stdout)
        return p.stdout


def gki_reference_patches(old,new):
    """Reference only changed patch sections; retain the native SELinux port.

    The Samsung port moves context in unchanged VFS/proc hunks. Reapplying
    those hunks to calculate an unrelated upstream delta is both unnecessary
    and incorrect. The native SukiSU port also deliberately removes the
    legacy manual hooks in these two files; they must not be merged back.
    """
    def sections(patch):
        result={}
        for part in re.split(rb'(?=^diff --git )',patch,flags=re.M):
            if not part.strip():continue
            match=re.match(rb'diff --git a/([^\s]+) b/([^\s]+)\r?\n',part)
            if not match or match[1]!=match[2]:
                raise RuntimeError('Unsupported upstream GKI patch path/rename')
            name=str(safe_relative(match[1].decode()))
            if name in result:raise RuntimeError('Duplicate upstream GKI patch section: '+name)
            for marker in (b'--- a/',b'+++ b/'):
                if not re.search(rb'^'+re.escape(marker+match[1])+rb'\r?$',part,re.M):
                    raise RuntimeError('Unsupported upstream GKI file creation/deletion: '+name)
            result[name]=part
        return result
    before,after=sections(old),sections(new)
    if before.keys()!=after.keys():
        raise RuntimeError('Upstream GKI patch file layout changed; explicit compatibility review required')
    changed=sorted(name for name in before if before[name]!=after[name])
    native={'security/selinux/hooks.c','security/selinux/selinuxfs.c'}
    excluded=[name for name in changed if name in native]
    paths=[name for name in changed if name not in native]
    return [b''.join(table[name] for name in paths) for table in (before,after)],paths,excluded


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
    reference_paths=[];native_exclusions=[]
    patch_name='kernel_patches/50_add_susfs_in_gki-android14-6.1.patch'
    if patch_name in changed:
        patches=[get(old,patch_name),get(new,patch_name)]
        if any(p is None for p in patches):raise RuntimeError('Upstream GKI patch was removed')
        patches,reference_paths,native_exclusions=gki_reference_patches(*patches)
        touched=set(reference_paths)
        trees=[work/'old-patched',work/'new-patched']
        for tree,patch in zip(trees,patches):
            tree.mkdir();command('git','init','-q',tree)
            for name in touched:
                original=common/name
                if original.is_file():
                    dest=tree/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(original,dest)
            if touched:
                command('git','-C',tree,'apply','--check','-',input=patch)
                command('git','-C',tree,'apply','-',input=patch)
        for name in touched:
            pair=[(tree/name).read_bytes() if (tree/name).exists() else None for tree in trees]
            if name=='security/selinux/ss/services.c' and all(p is not None for p in pair) and only_legacy_services_additions(*pair):
                native_exclusions.append(name)
            else:records[name]=pair
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
    (work/'upstream-changes.json').write_text(json.dumps({'old':old,'new':new,'all_changed_files':changed,'effective_files':list(serial),
        'gki_reference_paths':reference_paths,'native_selinux_excluded_legacy_paths':native_exclusions,
        'selinux_policy':'SukiSU native implementation; legacy manual hooks remain excluded by the audited port'},indent=2)+'\n')
    print('Official SuSFS delta:',len(serial),'effective kernel files;',len(changed),'upstream files')


def sync_susfs(common,ksu):
    root,plan=context();work=root/'.build-center-susfs';records=json.loads((work/'delta.json').read_text())
    results={};conflicts=[]
    for name,item in records.items():
        safe_relative(name);p=common/name
        values=[(work/item[k]).read_bytes() if item[k] is not None else None for k in ('base','target')]
        local=p.read_bytes() if p.exists() else None
        try:results[name]=three_way(local,*values)
        except SusfsMergeConflict as error:
            # Preserve all three public kernel source versions in the already
            # uploaded source-evidence audit, without changing the live tree.
            conflicts.append({'path':name,'local':local.decode(),'base':values[0].decode(),
                              'target':values[1].decode(),'merge_output':error.output.decode(errors='replace')})
            print('SuSFS merge conflict:',name,flush=True)
    if conflicts:
        audit=work/'upstream-changes.json';evidence=json.loads(audit.read_text())
        evidence['merge_conflicts']=conflicts
        audit.write_text(json.dumps(evidence,indent=2)+'\n')
        raise RuntimeError('SuSFS source conflicts: '+', '.join(c['path'] for c in conflicts)+'. Exact sources saved in source evidence.')
    # Validate the audited priority overlay before updating it from the pinned
    # upstream delta. Its exact-C semantic tests run after this integration.
    code=plan['sukisu_code'];h=root/'android14-6.1/build-helpers'
    priority=module(h/f'susfs-priority-uid-{code}/apply.py','center_priority_before_merge')
    priority_state=priority.verify(common,ksu)
    priority_text=results.get('fs/susfs.c',(common/'fs/susfs.c').read_bytes()).decode()
    refreshed=dict(priority_state,functions_sha256={name:digest(priority.body(priority_text,name).encode()) for name in priority.NAMES},
                   effective_source_pin=plan['susfs_commit'],prior_functions_sha256=priority_state['functions_sha256'])
    # All merges must succeed before any effective kernel source is changed.
    for name,data in results.items():
        p=common/name
        if data is None:
            if p.exists():p.unlink()
        else:p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    (common/'.susfs-priority-uid.json').write_text(json.dumps(refreshed,indent=2)+'\n')
    header=(common/'include/linux/susfs.h').read_text()
    if not re.search(r'^#define\s+SUSFS_VERSION\s+"'+re.escape(plan['susfs_version'])+'"',header,re.M):
        raise RuntimeError('Merged SuSFS version does not match pinned upstream')
    native(common,ksu,plan['sukisu_commit'])
    receipt={'source_pin':plan['susfs_commit'],'release_base':plan['susfs_release_base'],
             'susfs_version':plan['susfs_version'],'updated_files':list(results),'conflicts':0,
             'merge_policy':'SUSFS directive annotations and the legacy SELinux heading are non-semantic; C code conflicts remain fatal.',
             'effective_source_sha256':dict({name:digest(data) for name,data in results.items() if data is not None},
                                            **{'include/linux/susfs.h':digest((common/'include/linux/susfs.h').read_bytes())})}
    (common/'.build-center-susfs-update.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('PASS: official SuSFS delta merged without conflicts')


def wire_suspath(common,ksu,verify_only=False):
    root,plan=context();header=(common/'include/linux/susfs_def.h').read_text()
    if 'CMD_SUSFS_SET_SUS_PATH_UID_FILTER' not in header:return None
    if not re.search(r'^#define CMD_SUSFS_SET_SUS_PATH_UID_FILTER 0x55554$',header,re.M):
        raise RuntimeError('SUS_PATH command ABI changed')
    source=(common/'fs/susfs.c').read_text(encoding='utf-8')
    for name in ('susfs_set_sus_path_uid_filter','susfs_parse_sus_path_app_strings','susfs_is_uid_allowed_for_sus_path'):
        if not re.search(r'^(?:static )?(?:void|bool) '+name+r'\([^;]*\)\s*\{',source,re.M):
            raise RuntimeError('SUS_PATH implementation missing: '+name)
    case=('#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n'
          '    case CMD_SUSFS_SET_SUS_PATH_UID_FILTER: {\n'
          '        susfs_set_sus_path_uid_filter(arg);\n        return 0;\n    }\n#endif\n')
    refresh=('#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n'
             '    /* Refresh only after throne tracking, outside fsnotify locks. */\n'
             '    susfs_parse_sus_path_app_strings();\n#endif\n')
    dispatch=ksu/'kernel/supercall/dispatch.c';observer=ksu/'kernel/manager/pkg_observer.c'
    before_d=dispatch.read_text();before_o=observer.read_text();after_d=before_d;after_o=before_o
    if 'case CMD_SUSFS_SET_SUS_PATH_UID_FILTER:' not in after_d:
        anchor='#ifdef CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER\n    case CMD_SUSFS_SET_PRIORITY_UID_FILTER:'
        if after_d.count(anchor)!=1:raise RuntimeError('SUS_PATH dispatcher anchor changed')
        after_d=after_d.replace(anchor,case+anchor)
    if '    susfs_parse_sus_path_app_strings();' not in after_o:
        anchor=('#ifdef CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER\n'
                '    /* Resolve after throne tracking, outside fsnotify locks. */\n'
                '    susfs_parse_priority_app_strings();\n#endif\n')
        if after_o.count(anchor)!=1:raise RuntimeError('SUS_PATH refresh anchor changed')
        after_o=after_o.replace(anchor,anchor+refresh)
    include='#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs.h>\n#endif'
    if after_o.count(include)!=1:raise RuntimeError('SUS_PATH include anchor changed')
    if after_d.count(case)!=1 or after_o.count(refresh)!=1:
        raise RuntimeError('SUS_PATH control wiring drift')
    receipt={'source_pin':plan['susfs_commit'],'sukisu_pin':plan['sukisu_commit'],'command':'0x55554',
             'dispatcher_case_sha256':digest(case.encode()),'refresh_block_sha256':digest(refresh.encode()),
             'new_filter_wired':True,'native_uapi_unchanged':True}
    path=common/'.build-center-suspath-uid.json'
    if verify_only:
        if before_d!=after_d or before_o!=after_o or not path.exists() or json.loads(path.read_text())!=receipt:
            raise RuntimeError('SUS_PATH source wiring was not prepared or changed')
    else:
        dispatch.write_text(after_d,encoding='utf-8',newline='\n');observer.write_text(after_o,encoding='utf-8',newline='\n')
        path.write_text(json.dumps(receipt,indent=2)+'\n')
        print('PASS: official SUS_PATH UID command and package refresh wired into native SukiSU')
    return receipt


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
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('susfs-before','susfs-after','susfs-wire','capture-final','update-tool'));p.add_argument('--common',type=Path);p.add_argument('--ksu',type=Path)
    a=p.parse_args()
    if a.mode=='update-tool':update_tool()
    elif a.common is None:p.error('--common is required for kernel operations')
    elif a.mode=='susfs-before':prepare_susfs(a.common)
    elif a.mode=='susfs-after':sync_susfs(a.common,a.ksu)
    elif a.mode=='susfs-wire':wire_suspath(a.common,a.ksu)
    else:check(a.common,a.ksu,final_capture=True)
