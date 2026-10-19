#!/usr/bin/env python3
"""Verify the compiled-source receipt after downstream patches and before packaging."""
from pathlib import Path
import argparse,json,hashlib,subprocess
import apply as port
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--common',type=Path,required=True);p.add_argument('--ksu',type=Path,required=True);p.add_argument('--config',type=Path);a=p.parse_args()
proof=json.loads((port.HERE/'PREFLIGHT.json').read_text())
for file,key in ((port.HERE/'apply.py','apply_sha256'),(port.HERE/'compat.patch','compat_patch_sha256'),(port.HERE.parent/'su-session-41027/apply.py','session_helper_sha256')):
    if port.sha(file.read_bytes())!=proof[key]:raise RuntimeError('Preflight helper drift: '+str(file))
port.native(a.common,a.ksu)
for name,digest in proof['effective_kernel_sources_sha256'].items():
    file=a.ksu/name
    data=file.readlink().as_posix().encode() if file.is_symlink() else file.read_bytes()
    if port.sha(data)!=digest:raise RuntimeError('SukiSU compiled-source drift: '+name)
subprocess.run(['python3',str(port.HERE.parent/'configure-sukisu-41027.py'),str(a.ksu),'--verify-only'],check=True)
if a.config:
    lines=a.config.read_text().splitlines()
    for required in ('CONFIG_KSU=y','CONFIG_KSU_SUSFS=y','CONFIG_KALLSYMS_ALL=y'):
        if required not in lines:raise RuntimeError('Missing '+required)
    for forbidden in ('CONFIG_KSU=m','CONFIG_KPM=y','CONFIG_CGROUP_PIDS=y','CONFIG_CFS_BANDWIDTH=y'):
        if forbidden in lines:raise RuntimeError('Wrong target profile: '+forbidden)
print('PASS: audited SukiSU41027 compiled sources, native SELinux and exact target profile')
