#!/usr/bin/env python3
"""Deterministic SukiSU41013 kernel identity; no remote version/count fallback."""
from pathlib import Path
import argparse,subprocess,re
PIN='ffa00c0700604216de8a86ad9c74226af1add0d5'
def configure(root,verify=False):
    if subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()!=PIN:raise RuntimeError('Wrong SukiSU pin')
    count=int(subprocess.check_output(['git','-C',str(root),'rev-list','--count','HEAD']))
    if count!=3828 or 40000+count-2815!=41013:raise RuntimeError('SukiSU41013 source count mismatch')
    path=root/'kernel/Kbuild';text=path.read_text()
    settings={'KSU_GITHUB_VER':'','GITHUB_COMMITS':'','LOCAL_COUNT':'3828','KSU_VERSION':'41013','VERSION_TAG':'4.2.1','KSU_VERSION_FULL':'v4.2.1-41013-ffa00c07'}
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
    print('PASS: immutable SukiSU41013 kernel identity and official manager certificate')
