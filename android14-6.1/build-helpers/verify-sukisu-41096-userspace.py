#!/usr/bin/env python3
"""Verify native SukiSU41096 workspace inputs, generated UAPI6 and ARM64 outputs."""
from pathlib import Path
import argparse,hashlib,json,subprocess
import sukisu_41096_lock as lock
import sukisu_41096_uapi as uapi
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);p.add_argument('--receipt',type=Path,required=True);p.add_argument('--verify-build',action='store_true');p.add_argument('--build-messages',type=Path);a=p.parse_args();root=a.source.resolve()
result={'pin':lock.PIN,'version':41096,'version_formula':'40000 + 3911 - 2815','lock':lock.verify(root),'uapi':uapi.verify_sources(root),'device_runtime_tested':False,'build_verified':False}
paths=['Cargo.toml','Cargo.lock','userspace/ksud/Cargo.toml','userspace/ksuinit/Cargo.toml','userspace/ksud/build.rs','userspace/ksud/src/defs.rs']
for path in paths:
    if path!='Cargo.lock' and (root/path).read_bytes()!=lock.upstream(root,path):raise RuntimeError('Upstream source drift: '+path)
result['inputs_sha256']={path:sha(root/path) for path in paths}
if a.verify_build:
    previous=json.loads(a.receipt.read_text())
    for key in ('pin','version','lock','uapi','inputs_sha256'):
        if previous[key]!=result[key]:raise RuntimeError('Build input changed: '+key)
    outputs={}
    for crate in ('ksud','ksuinit'):
        path=root/f'target/aarch64-linux-android/release/{crate}';data=path.read_bytes()
        if len(data)<64 or data[:6]!=b'\x7fELF\x02\x01' or int.from_bytes(data[18:20],'little')!=183:raise RuntimeError('Invalid ARM64 ELF: '+crate)
        outputs[crate]={'sha256':sha(path),'size':len(data)}
    data=(root/'target/aarch64-linux-android/release/ksud').read_bytes()
    for token in (b'41096',b'com.sukisu.ultra'):
        if token not in data:raise RuntimeError('ksud identity absent: '+repr(token))
    result.update(build_verified=True,binaries=outputs,generated_uapi=uapi.verify_bindings(root,a.build_messages))
a.receipt.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
