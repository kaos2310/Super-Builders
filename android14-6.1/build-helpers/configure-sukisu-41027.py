#!/usr/bin/env python3
"""Deterministic SukiSU41027 kernel identity; no remote version/count fallback."""
from pathlib import Path
import argparse,subprocess,re
PIN='31255c460caefef75e98b3406dd40efcc00fad38'
def configure(root,verify=False):
    if subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()!=PIN:raise RuntimeError('Wrong SukiSU pin')
    count=int(subprocess.check_output(['git','-C',str(root),'rev-list','--count','HEAD']))
    if count!=3842 or 40000+count-2815!=41027:raise RuntimeError('SukiSU41027 source count mismatch')
    path=root/'kernel/Kbuild';text=path.read_text()
    settings={'KSU_GITHUB_VER':'','GITHUB_COMMITS':'','LOCAL_COUNT':'3842','KSU_VERSION':'41027','VERSION_TAG':'4.2.1','KSU_VERSION_FULL':'v4.2.1-41027-31255c46'}
    for name,value in settings.items():
        pattern=r'^'+name+r'\s*:=.*$';replacement=name+' := '+value
        if verify:
            if len(re.findall(pattern,text,re.M))!=1 or replacement not in text:raise RuntimeError('Kernel identity drift: '+name)
        else:
            text,n=re.subn(pattern,replacement,text,flags=re.M)
            if n!=1:raise RuntimeError('Ambiguous Kbuild assignment: '+name)
    if not verify:path.write_text(text,encoding='utf-8',newline='\n')
    if 'com.sukisu.ultra' not in text or '947ae944f3de4ed4c21a7e4f7953ecf351bfa2b36239da37a34111ad29993eef' not in text:raise RuntimeError('Official SukiSU manager identity lost')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--verify-only',action='store_true');a=p.parse_args();configure(a.source,a.verify_only)
    print('PASS: immutable SukiSU41027 kernel identity and official manager certificate')
