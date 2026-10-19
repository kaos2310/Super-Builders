#!/usr/bin/env python3
"""Evidence-gated built-in SukiSU41027/SUSFS port for Samsung Linux 6.1.162."""
from pathlib import Path
import argparse,hashlib,json,subprocess,re,importlib.util
HERE=Path(__file__).resolve().parent
PIN='31255c460caefef75e98b3406dd40efcc00fad38'
MANUAL=('security/selinux/hooks.c','security/selinux/selinuxfs.c')
def sha(data):return hashlib.sha256(data).hexdigest()
def git(root,*args,**kw):return subprocess.check_output(['git','-C',str(root),*map(str,args)],**kw)
def native(common,ksu):
    if (ksu/'kernel/feature/selinux_hide.c').read_bytes()!=git(ksu,'show',PIN+':kernel/feature/selinux_hide.c'):raise RuntimeError('Native SukiSU SELinux implementation changed')
    for name in MANUAL:
        text=(common/name).read_text()
        if any(x in text for x in ('fake_state','ksu_selinux_hide_running','my_setprocattr','my_sel_open_handle_status')):raise RuntimeError('Parallel manual SELinux hook: '+name)
    if 'susfs_is_avc_log_spoofing_enabled' not in (common/'security/selinux/avc.c').read_text():raise RuntimeError('SUSFS AVC logging lost')
def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('common','ksu','patch'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--evidence',type=Path,required=True);a=p.parse_args()
    if git(a.ksu,'rev-parse','HEAD').decode().strip()!=PIN:raise RuntimeError('Exact SukiSU41027 required')
    text=(a.common/'Makefile').read_text()
    if not all(re.search(r'^'+k+' = '+v+'$',text,re.M) for k,v in [('VERSION','6'),('PATCHLEVEL','1'),('SUBLEVEL','162')]):raise RuntimeError('Port restricted to Samsung Linux 6.1.162')
    patch=a.patch.read_bytes();compat=(HERE/'compat.patch').read_bytes();proof=json.loads(a.evidence.read_text())
    required={'pin':PIN,'kernel_patch_sha256':sha(patch),'compat_patch_sha256':sha(compat),'apply_sha256':sha(Path(__file__).read_bytes()),'session_helper_sha256':sha((HERE.parent/'su-session-41027/apply.py').read_bytes()),'mount_hide_test_sha256':sha((HERE.parent/'test-sukisu-41027-mount-hide.py').read_bytes()),'extension_test_sha256':sha((HERE.parent/'test-sukisu-41027-extension.py').read_bytes())}
    for key,value in required.items():
        if proof.get(key)!=value:raise RuntimeError('Independent preflight mismatch: '+key)
    for key in ('arm64_sukisu_subtree_compiled','arm64_selinux_objects_compiled','session_fault_tests_passed','uapi6_service_tests_passed','fresh_replay_matches_compiled_sources','mount_hide_susfs_callback_tests_passed','native_extension_tests_passed'):
        if proof.get(key) is not True:raise RuntimeError('Missing independent evidence: '+key)
    parts=re.split(r'(?=^diff --git )',patch.decode(),flags=re.M)
    selected=[c for c in parts if any(c.startswith('diff --git a/'+n+' b/'+n+'\n') for n in MANUAL)]
    if len(selected)!=2:raise RuntimeError('Expected two manual SELinux sections')
    reverse=''.join(selected).encode()
    git(a.ksu,'apply','--check','-',input=compat,stderr=subprocess.STDOUT)
    git(a.common,'apply','--reverse','--check','-',input=reverse,stderr=subprocess.STDOUT)
    git(a.ksu,'apply','-',input=compat)
    git(a.common,'apply','--reverse','-',input=reverse)
    subprocess.run(['python3',str(HERE.parent/'configure-sukisu-41027.py'),str(a.ksu)],check=True)
    native(a.common,a.ksu)
    (a.common/'.sukisu-41027-susfs-port.json').write_text(json.dumps(required,indent=2)+'\n')
    print('PASS: matched independent SukiSU41027/SUSFS port, native SELinux, PREINIT disabled')
if __name__=='__main__':main()
