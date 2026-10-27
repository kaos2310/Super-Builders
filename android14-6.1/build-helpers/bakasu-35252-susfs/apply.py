#!/usr/bin/env python3
"""Exact Linux 6.1.162 port: retain SUSFS and use BakaSU's native SELinux hooks.

Only the two obsolete fake_state manual-hook patches are reversed. AVC logging
and all filesystem SUSFS changes stay intact. Upstream no longer blocks SUSFS;
its compatibility Makefile remains byte-identical. Independent compilation and
fault-injection evidence is still required for the local manual-hook removal.
"""
import argparse, hashlib, json, re, subprocess
from pathlib import Path

PIN='d5e9e025b8b49155f8014684d64c91742b465f65'
MANUAL=('security/selinux/hooks.c','security/selinux/selinuxfs.c')
HERE=Path(__file__).resolve().parent
def sha(data): return hashlib.sha256(data).hexdigest()
def run(*args,**kw): return subprocess.check_output([str(a) for a in args],**kw)

def selected_patch(data):
    chunks=re.split(r'(?=^diff --git )',data,flags=re.M)
    selected=[c for c in chunks if any(c.startswith('diff --git a/'+p+' b/'+p+'\n') for p in MANUAL)]
    if len(selected)!=2:raise RuntimeError('Expected exactly two obsolete manual SELinux patch sections')
    return ''.join(selected).encode()

def verify(common,ksu):
    for name in MANUAL:
        text=(common/name).read_text()
        for token in ('fake_state','ksu_selinux_hide_running','my_setprocattr','my_write_context','my_write_access','my_sel_open_handle_status'):
            if token in text:raise RuntimeError('Obsolete SUSFS SELinux hook remains: '+name+':'+token)
    source=(ksu/'kernel/feature/selinux_hide.c').read_bytes()
    upstream=run('git','-C',ksu,'show',PIN+':kernel/feature/selinux_hide.c')
    if source!=upstream:raise RuntimeError('New BakaSU native SELinux implementation changed')
    if b'KSU_LSM_HOOK_INIT(setprocattr' not in source:raise RuntimeError('Native LSM hook absent')
    if 'susfs_is_avc_log_spoofing_enabled' not in (common/'security/selinux/avc.c').read_text():
        raise RuntimeError('SUSFS AVC logging feature lost')
    return {p:sha((common/p).read_bytes()) for p in MANUAL}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('common','ksu','patch'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--evidence',type=Path)
    parser.add_argument('--preflight',action='store_true',help='Apply only in the explicit isolated compiler preflight')
    args=parser.parse_args(); common=args.common; ksu=args.ksu
    if run('git','-C',ksu,'rev-parse','HEAD').decode().strip()!=PIN:raise RuntimeError('Exact BakaSU35252 required')
    makefile=(common/'Makefile').read_text()
    if not all(re.search(r'^'+k+r' = '+v+r'$',makefile,re.M) for k,v in [('VERSION','6'),('PATCHLEVEL','1'),('SUBLEVEL','162')]):
        raise RuntimeError('Port restricted to Linux 6.1.162')
    patch=args.patch.read_bytes(); changes=selected_patch(patch.decode())
    if not args.preflight:
        if not args.evidence:raise RuntimeError('Independent preflight evidence is required before source changes')
        evidence=json.loads(args.evidence.read_text())
        for key in ('arm64_selinux_objects_compiled','arm64_bakasu_objects_compiled','session_fault_injection_passed','uapi_services_passed'):
            if evidence.get(key) is not True:raise RuntimeError('Missing preflight proof: '+key)
        if evidence['bakasu_pin']!=PIN or evidence['patch_sha256']!=sha(patch) or evidence['port_sha256']!=sha(Path(__file__).read_bytes()):
            raise RuntimeError('Preflight evidence does not match this port')
    target=ksu/'kernel/tools/susfs_compat.mk'
    original=run('git','-C',ksu,'show',PIN+':kernel/tools/susfs_compat.mk')
    if target.read_bytes()!=original:raise RuntimeError('SUSFS compatibility Makefile differs from exact upstream')
    if b'$(error Please wait susfs update.)' in original:raise RuntimeError('Unexpected upstream build block')
    # Validate every reverse hunk before any writes. This preserves adjacent changes.
    run('git','-C',common,'apply','--reverse','--check','-',input=changes,stderr=subprocess.STDOUT)
    run('git','-C',common,'apply','--reverse','-',input=changes)
    verified=verify(common,ksu)
    state={'bakasu_pin':PIN,'mode':'isolated-preflight' if args.preflight else 'independently-audited-native-selinux',
           'manual_hook_files':verified,'patch_sha256':sha(patch),'native_selinux_sha256':sha((ksu/'kernel/feature/selinux_hide.c').read_bytes()),
           'native_port_approved':not args.preflight,'upstream_compat_makefile_unchanged':True,
           'upstream_build_block_present':False,'device_runtime_tested':False}
    (common/'.bakasu-35252-susfs-port.json').write_text(json.dumps(state,indent=2)+'\n')
    print(json.dumps(state,indent=2))

if __name__=='__main__':main()
