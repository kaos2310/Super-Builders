#!/usr/bin/env python3
"""Exact SukiSU41013 workspace lock repair: three stale dependency edges only."""
from pathlib import Path
import subprocess,hashlib,argparse,json,tomllib,sys
PIN='ffa00c0700604216de8a86ad9c74226af1add0d5'
def upstream(root,path):return subprocess.check_output(['git','-C',str(root),'show',PIN+':'+path])
def expected(root):
    assert subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()==PIN
    for path in ('Cargo.toml','userspace/ksud/Cargo.toml','userspace/ksuinit/Cargo.toml'):
        if (root/path).read_bytes()!=upstream(root,path):raise RuntimeError('Manifest drift: '+path)
    original=upstream(root,'Cargo.lock');before=tomllib.loads(original.decode())
    old=b' "bitflags 2.13.1",';new=b' "bitflags 2.13.2",'
    if original.count(old)!=3 or original.count(b'name = "bitflags"')!=2:raise RuntimeError('Unexpected upstream bitflags lock structure')
    fixed=original.replace(old,new);after=tomllib.loads(fixed.decode())
    changed=[]
    for a,b in zip(before['package'],after['package']):
        if a!=b:
            assert a['name'] in ('kqueue-sys','notify','redox_syscall')
            assert {k:v for k,v in a.items() if k!='dependencies'}=={k:v for k,v in b.items() if k!='dependencies'}
            changed.append(a['name'])
    assert set(changed)=={'kqueue-sys','notify','redox_syscall'}
    return original,fixed
def verify(root):
    original,fixed=expected(root)
    if (root/'Cargo.lock').read_bytes()!=fixed:raise RuntimeError('Lock differs from exact audited edge correction')
    return {'pin':PIN,'upstream_sha256':hashlib.sha256(original).hexdigest(),'effective_sha256':hashlib.sha256(fixed).hexdigest(),'changed_edges':3,'package_versions_changed':False}
def apply(root):
    original,fixed=expected(root);path=root/'Cargo.lock'
    if path.read_bytes() not in (original,fixed):raise RuntimeError('Refusing unexpected workspace lock')
    path.write_bytes(fixed);return verify(root)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--verify-only',action='store_true');a=p.parse_args()
    print(json.dumps((verify if a.verify_only else apply)(a.source),indent=2))
