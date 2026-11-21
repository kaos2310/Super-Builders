"""Prune only reviewed unreachable Cargo.lock entries; never re-resolve versions."""
from pathlib import Path
import hashlib
import re
import subprocess
import tomllib

PIN='b2d01e8bcea80139be9076c63dcc9a6694691d72'
UPSTREAM_SHA256='c300384bd4f6be1c1b8c9dea049c21aa53febe2fde6a5320cc34f27caa30da9a'
EFFECTIVE_SHA256='e19a56db309de04e02063beda15acad58702cb6a203a17766e163cc4e629762e'


def digest(raw):return hashlib.sha256(raw).hexdigest()


def upstream(root,pin,path):
    return subprocess.check_output(['git','-C',str(root),'show',pin+':'+path])


def prune_unreachable(raw):
    data=tomllib.loads(raw.decode())
    if set(data)!={'version','package'} or data['version']!=4:
        raise RuntimeError('Unsupported reviewed lock layout')
    packages=data['package'];identity=lambda p:(p['name'],p['version'],p.get('source',''))
    if len({identity(p) for p in packages})!=len(packages):raise RuntimeError('Duplicate lock package')
    roots=[i for i,p in enumerate(packages) if 'source' not in p]
    if {packages[i]['name'] for i in roots}!={'ksud','ksuinit'}:raise RuntimeError('Unexpected workspace roots')
    reachable=set();stack=list(roots)
    while stack:
        i=stack.pop()
        if i in reachable:continue
        reachable.add(i)
        for dep in packages[i].get('dependencies',[]):
            match=re.fullmatch(r'([^ ]+)(?: ([^ (]+))?(?: \(([^)]+)\))?',dep)
            if not match:raise RuntimeError('Unsupported lock dependency')
            matches=[j for j,p in enumerate(packages) if p['name']==match[1]
                and (match[2] is None or p['version']==match[2]) and (match[3] is None or p.get('source')==match[3])]
            if len(matches)!=1:raise RuntimeError('Missing or ambiguous lock dependency: '+dep)
            stack.extend(matches)
    chunks=re.split(rb'(?=^\[\[package\]\]\n)',raw,flags=re.M)
    if len(chunks)!=len(packages)+1:raise RuntimeError('Lock section count changed')
    effective=chunks[0]+b''.join(c for i,c in enumerate(chunks[1:]) if i in reachable)
    expected=[p for i,p in enumerate(packages) if i in reachable]
    if tomllib.loads(effective.decode())['package']!=expected:
        raise RuntimeError('Retained dependency data changed')
    removed=[identity(p) for i,p in enumerate(packages) if i not in reachable]
    return effective,removed


def reviewed_lock(raw,pin):
    if pin!=PIN:return raw,[]
    if digest(raw)!=UPSTREAM_SHA256:raise RuntimeError('Reviewed upstream Cargo.lock changed')
    effective,removed=prune_unreachable(raw)
    if digest(effective)!=EFFECTIVE_SHA256 or len(removed)!=17:
        raise RuntimeError('Reviewed orphan-only Cargo.lock cleanup changed')
    return effective,removed


def inputs(root,pin):
    if subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD']).decode().strip()!=pin:
        raise RuntimeError('Native workspace pin mismatch')
    for path in ('Cargo.toml','userspace/ksud/Cargo.toml','userspace/ksuinit/Cargo.toml'):
        if (root/path).read_bytes()!=upstream(root,pin,path):raise RuntimeError('Native workspace drift: '+path)
    raw=upstream(root,pin,'Cargo.lock')
    if b' "bitflags 2.13.1",' in raw or len(tomllib.loads(raw.decode())['package'])<=200:
        raise RuntimeError('Unexpected native workspace dependency graph')
    effective,removed=reviewed_lock(raw,pin)
    return raw,effective,removed


def verify(root,pin):
    original,effective,removed=inputs(root,pin)
    if (root/'Cargo.lock').read_bytes()!=effective:raise RuntimeError('Effective Cargo.lock drift')
    return {'pin':pin,'upstream_sha256':digest(original),'effective_sha256':digest(effective),
            'changed_edges':0,'package_versions_changed':False,'removed_orphan_packages':[list(p) for p in removed],
            'scope':'Only unreachable entries removed; every retained package table is byte-identical.'}


def apply(root,pin):
    original,effective,_=inputs(root,pin)
    actual=(root/'Cargo.lock').read_bytes()
    if actual not in (original,effective):raise RuntimeError('Unexpected Cargo.lock before preparation')
    if actual!=effective:(root/'Cargo.lock').write_bytes(effective)
    return verify(root,pin)
