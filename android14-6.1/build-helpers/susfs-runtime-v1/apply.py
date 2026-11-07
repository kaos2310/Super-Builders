#!/usr/bin/env python3
"""Exact runtime overlay for SukiSU 41159; retains verifiable baseline sources."""
import argparse, gzip, hashlib, importlib.util, json, re, subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent
import sys
sys.dont_write_bytecode=True
sys.path.insert(0,str(HERE))
from transform import PIN, transform, once
STATE='.susfs-runtime-v1.json'
PATHS=('common/fs/susfs.c','common/include/linux/susfs_uid_gate.h','common/kernel/kallsyms.c','candidate/kernel/supercall/dispatch.c')
NEW=('common/include/linux/susfs_runtime.h','common/include/linux/susfs_runtime_abi.h','common/fs/susfs_runtime_impl.h')

def sha(data):return hashlib.sha256(data.encode() if isinstance(data,str) else data).hexdigest()
def file(common,ksu,name):
    group,relative=name.split('/',1)
    return (common if group=='common' else ksu)/relative
def identity(ksu):
    if subprocess.check_output(['git','-C',str(ksu),'rev-parse','HEAD'],text=True).strip()!=PIN:raise RuntimeError('Exact SukiSU 41159 required')
def undo(current):
    result=dict(current)
    name='common/fs/susfs.c'
    result[name]=once(result[name],'extern bool susfs_is_current_ksu_domain(void);\n#include "susfs_runtime_impl.h"','extern bool susfs_is_current_ksu_domain(void);')
    result[name]=once(result[name],'!susfs_runtime_enabled(SUSFS_RT_UNICODE) || !susfs_uid_gate_current()','!susfs_uid_gate_current()')
    old='!susfs_runtime_enabled(SUSFS_RT_HIDDEN_NAME) || !susfs_uid_gate_current()'
    if result[name].count(old)!=2:raise RuntimeError('Hidden-name runtime scope drift')
    result[name]=result[name].replace(old,'!susfs_uid_gate_current()')
    name='common/include/linux/susfs_uid_gate.h'
    result[name]=once(result[name],'#include <linux/cred.h>\n#include <linux/susfs_runtime.h>','#include <linux/cred.h>')
    result[name]=once(result[name],'\tif (!susfs_runtime_enabled(SUSFS_RT_UID_GATE))\n\t\treturn true; /* Legacy ungated consumers; does not change root authorization. */\n','')
    name='common/kernel/kallsyms.c'
    result[name]=once(result[name],'#include <linux/kallsyms.h>\n#include <linux/susfs_runtime.h>','#include <linux/kallsyms.h>')
    result[name]=once(result[name],'if (susfs_runtime_enabled(SUSFS_RT_SYMBOLS) &&\n\t\t    (susfs_starts_with(iter->name, "ksu_") ||','if (susfs_starts_with(iter->name, "ksu_") ||')
    result[name]=once(result[name],'susfs_starts_with(iter->name, "is_zygote")))','susfs_starts_with(iter->name, "is_zygote"))')
    name='candidate/kernel/supercall/dispatch.c'
    result[name]=once(result[name],'#include <linux/susfs.h>\n#include <linux/susfs_runtime.h>','#include <linux/susfs.h>')
    result[name]=once(result[name],'    case CMD_SUSFS_RUNTIME_GET:\n    case CMD_SUSFS_RUNTIME_SET:\n        return susfs_runtime_handle(cmd, *arg);','')
    # Forward insertion includes its leading newline; restore exact switch body.
    result[name]=once(result[name],'switch (cmd) {\n\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH','switch (cmd) {\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH')
    return result
def verify(common,ksu):
    identity(ksu)
    state=json.loads((common/STATE).read_text())
    if state['pin']!=PIN or state['protocol']!='kaoslab-susfs-runtime-v1':raise RuntimeError('Runtime receipt identity drift')
    current={n:file(common,ksu,n).read_text() for n in PATHS+NEW}
    if {n:sha(t) for n,t in current.items()}!=state['output_sha256']:raise RuntimeError('Runtime source drift')
    baseline=undo({n:current[n] for n in PATHS})
    if {n:sha(t) for n,t in baseline.items()}!=state['input_sha256']:raise RuntimeError('Runtime baseline reconstruction drift')
    if transform(baseline)!=current:raise RuntimeError('Runtime transformation/helper drift')
    return baseline
def apply(common,ksu):
    identity(ksu)
    if (common/STATE).exists():verify(common,ksu);return
    if any(file(common,ksu,n).exists() for n in NEW):raise RuntimeError('Partial runtime overlay')
    original={n:file(common,ksu,n).read_text() for n in PATHS}
    planned=transform(original)
    state={'protocol':'kaoslab-susfs-runtime-v1','pin':PIN,'base_run':42129383180,
        'input_sha256':{n:sha(t) for n,t in original.items()},'output_sha256':{n:sha(t) for n,t in planned.items()},'device_tested':False}
    for name,text in planned.items():
        p=file(common,ksu,name);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8',newline='\n')
    (common/STATE).write_text(json.dumps(state,indent=2)+'\n')
    verify(common,ksu)
def baseline_text(common,ksu,name):return verify(common,ksu)[name]
def attest(common,ksu,config,image,vmlinux):
    verify(common,ksu)
    text=config.read_text();blob=image.read_bytes()
    if blob.count(b'IKCFG_ST')!=1:raise RuntimeError('Unique Image IKCONFIG required')
    begin=blob.index(b'IKCFG_ST')+8;end=blob.index(b'IKCFG_ED',begin);embedded=gzip.decompress(blob[begin:end]).decode()
    symbols=('KSU_SUSFS','KSU_SUSFS_UID_GATED_HIDING','KSU_SUSFS_HIDDEN_NAME','KSU_SUSFS_UNICODE_FILTER','KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS','KPM','ZEROMOUNT')
    for symbol in symbols:
        for source in (text,embedded):
            if re.findall(r'^CONFIG_'+symbol+r'=.*$',source,re.M)!=['CONFIG_'+symbol+'=y']:raise RuntimeError('Missing compiled option '+symbol)
    names=set(re.findall(r'\b(susfs_runtime_handle|susfs_runtime_enabled)\s*$',subprocess.check_output(['nm',str(vmlinux)],text=True),re.M))
    if names!={'susfs_runtime_handle','susfs_runtime_enabled'}:raise RuntimeError('Runtime functions absent from linked vmlinux')
    state=json.loads((common/STATE).read_text())
    return dict(state,image_sha256=sha(blob),vmlinux_sha256=sha(vmlinux.read_bytes()),config_sha256=sha(text),compiled_functions=sorted(names),runtime_defaults='all compiled features on',full_device_runtime_tested=False)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--common',type=Path,required=True);p.add_argument('--ksu',type=Path,required=True);p.add_argument('--verify-only',action='store_true');p.add_argument('--config',type=Path);p.add_argument('--image',type=Path);p.add_argument('--vmlinux',type=Path);p.add_argument('--receipt',type=Path);a=p.parse_args()
    if a.verify_only:verify(a.common,a.ksu)
    else:apply(a.common,a.ksu)
    result=json.loads((a.common/STATE).read_text())
    if a.config or a.image or a.vmlinux:
        if not all((a.config,a.image,a.vmlinux)):p.error('config, image and vmlinux required together')
        result=attest(a.common,a.ksu,a.config,a.image,a.vmlinux)
    if a.receipt:a.receipt.write_text(json.dumps(result,indent=2)+'\n')
    print('PASS: SukiSU41159 runtime overlay'+(' and linked Image' if a.image else ' source'))
