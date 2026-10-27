#!/usr/bin/env python3
"""Verify the immutable official SukiSU41096 workspace lock; no repair needed."""
from pathlib import Path
import subprocess,hashlib,argparse,json,tomllib
PIN="ad73573dd9ee66da86b2741e18d7e591999ade24"
def upstream(root,path):return subprocess.check_output(['git','-C',str(root),'show',PIN+':'+path])
def verify(root):
    assert subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()==PIN
    for path in ('Cargo.toml','Cargo.lock','userspace/ksud/Cargo.toml','userspace/ksuinit/Cargo.toml'):
        if (root/path).read_bytes()!=upstream(root,path):raise RuntimeError('Native workspace drift: '+path)
    original=upstream(root,'Cargo.lock');data=tomllib.loads(original.decode())
    assert b' "bitflags 2.13.1",' not in original
    assert len(data['package'])>200
    return {'pin':PIN,'upstream_sha256':hashlib.sha256(original).hexdigest(),'effective_sha256':hashlib.sha256(original).hexdigest(),'changed_edges':0,'package_versions_changed':False}
def apply(root):return verify(root)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--verify-only',action='store_true');a=p.parse_args();print(json.dumps(verify(a.source),indent=2))
