#!/usr/bin/env python3
"""Bounded official SUSFS priority-UID backport for Samsung Android14/6.1.162."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,gzip
HERE=Path(__file__).resolve().parent
STATE='.susfs-priority-uid.json'
NAMES=('susfs_is_valid_app_name','susfs_resolve_priority_app_uid','susfs_parse_priority_app_names','susfs_set_priority_uid_filter','susfs_priority_app_strings_worker','susfs_parse_priority_app_strings','susfs_is_priority_uid_filtered')

def sha(data):return hashlib.sha256(data).hexdigest()

def body(text,name):
    found=list(re.finditer(r'^(?:static )?(?:int|void|bool) '+name+r'\([^;]*?\)\s*\{',text,re.M))
    if len(found)!=1:raise RuntimeError('Expected one filter function: '+name)
    a=found[0].start();p=found[0].end();depth=1
    # These official functions contain no braces in string literals or comments.
    while depth:
        depth+=(text[p]=='{')-(text[p]=='}');p+=1
    return text[a:p]

def verify(common,ksu=None,config=None):
    state=json.loads((common/STATE).read_text());source=json.loads((HERE/'SOURCE.json').read_text())
    if state['common_patch_sha256']!=sha((HERE/'common.patch').read_bytes()) or state['upstream_commit']!=source['upstream_commit']:
        raise RuntimeError('Priority filter source binding changed')
    text=(common/'fs/susfs.c').read_text()
    if {name:sha(body(text,name).encode()) for name in NAMES}!=state['functions_sha256']:
        raise RuntimeError('Priority filter code drift')
    for name in ('block/ioprio.c','kernel/sys.c'):
        text=(common/name).read_text()
        if text.count('susfs_is_priority_uid_filtered(uid.val)')!=2:
            raise RuntimeError('Missing priority syscall hooks: '+name)
    if ksu:
        dispatch=(ksu/'kernel/supercall/dispatch.c').read_text()
        if not re.search(r'case CMD_SUSFS_SET_PRIORITY_UID_FILTER:\s*\{\s*susfs_set_priority_uid_filter\(arg\);\s*return 0;',dispatch):
            raise RuntimeError('Priority command dispatcher missing')
        observer=(ksu/'kernel/manager/pkg_observer.c').read_text()
        if not re.search(r'track_throne\(false\);\s*#ifdef CONFIG_KSU_SUSFS\s*/\*[^*]*\*/\s*susfs_parse_priority_app_strings\(\);',observer):
            raise RuntimeError('Priority refresh must run after throne tracking')
    if config and 'CONFIG_KSU_SUSFS=y' not in config.read_text().splitlines():
        raise RuntimeError('Priority filter requires built-in SUSFS')
    return state

def apply(common):
    if (common/STATE).exists():return verify(common)
    source=json.loads((HERE/'SOURCE.json').read_text());patch=(HERE/'common.patch').read_bytes()
    if sha(patch)!=source['common_patch_sha256']:raise RuntimeError('Priority patch hash mismatch')
    make=(common/'Makefile').read_text()
    if not all(re.search(r'^'+k+' = '+v+'$',make,re.M) for k,v in [('VERSION','6'),('PATCHLEVEL','1'),('SUBLEVEL','162')]):
        raise RuntimeError('Priority backport restricted to audited Linux 6.1.162')
    for args in (('apply','--check','-'),('apply','-')):
        subprocess.run(['git','-C',str(common),*args],input=patch,check=True)
    text=(common/'fs/susfs.c').read_text()
    state=dict(source,functions_sha256={name:sha(body(text,name).encode()) for name in NAMES})
    (common/STATE).write_text(json.dumps(state,indent=2)+'\n')
    return verify(common)

def attest(state,config,image,vmlinux,nm):
    blob=image.read_bytes()
    if blob.count(b'IKCFG_ST')!=1:raise RuntimeError('Expected one embedded kernel config')
    start=blob.index(b'IKCFG_ST')+8;end=blob.index(b'IKCFG_ED',start)
    embedded=gzip.decompress(blob[start:end])
    for value in (config.read_bytes(),embedded):
        if b'CONFIG_KSU_SUSFS=y' not in value.splitlines():raise RuntimeError('Packaged priority filter lacks built-in SUSFS')
    symbols=subprocess.check_output([nm,'--defined-only',str(vmlinux)],text=True)
    required=('susfs_set_priority_uid_filter','susfs_is_priority_uid_filtered','susfs_parse_priority_app_strings')
    for name in required:
        if not re.search(r'^[0-9a-fA-F]+ [tT] '+name+r'(?:\.llvm\.[0-9]+)?$',symbols,re.M):raise RuntimeError('Priority filter missing from linked kernel: '+name)
    if b'CMD_SUSFS_SET_PRIORITY_UID_FILTER' not in blob:raise RuntimeError('Priority command missing from packaged Image')
    return dict(state,image_sha256=sha(blob),vmlinux_sha256=sha(vmlinux.read_bytes()),embedded_config_sha256=sha(embedded),compiled_functions=list(required),device_tested=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--common',type=Path,required=True);p.add_argument('--ksu',type=Path);p.add_argument('--config',type=Path);p.add_argument('--verify-only',action='store_true')
    p.add_argument('--image',type=Path);p.add_argument('--vmlinux',type=Path);p.add_argument('--receipt',type=Path);p.add_argument('--nm',default='nm');a=p.parse_args()
    result=verify(a.common,a.ksu,a.config) if a.verify_only else apply(a.common)
    if any((a.image,a.vmlinux,a.receipt)):
        if not all((a.config,a.image,a.vmlinux,a.receipt)):p.error('Artifact audit requires config, image, vmlinux and receipt')
        result=attest(result,a.config,a.image,a.vmlinux,a.nm)
        a.receipt.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
