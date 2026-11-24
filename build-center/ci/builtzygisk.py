"""Stage and verify the complete pinned upstream ARM64 BuiltZygisk payload."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tomllib
import zipfile

if __package__:
    from .forgejo import BUILT_ZYGISK_PIN as PIN
else:
    from forgejo import BUILT_ZYGISK_PIN as PIN
FILES = {
    'zygiskd': ('bin/arm64-v8a/zygiskd', 2, 183),
    'zygisk-ptrace': ('lib/arm64-v8a/libzygisk_ptrace.so', 2, 183),
    'libzygisk.so': ('lib/arm64-v8a/libzygisk.so', 2, 183),
    'libzygisk32.so': ('lib/armeabi-v7a/libzygisk.so', 1, 40),
    'zygisk-module.prop': ('module.prop', None, None),
}
DEPS = ('lsplt', 'dobby', 'rv64hook', 'yukiplt')

def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()

def sha(data):
    return hashlib.sha256(data).hexdigest()

def inputs(nova):
    source = nova / 'external/BuiltZygisk'
    if git(nova, 'ls-tree', 'HEAD', 'external/BuiltZygisk').split()[2] != PIN:
        raise RuntimeError('Nova BuiltZygisk gitlink changed')
    if git(source, 'rev-parse', 'HEAD') != PIN:
        raise RuntimeError('BuiltZygisk checkout does not match Nova')
    subprocess.run(['git', '-C', str(source), 'diff', '--exit-code'], check=True)
    deps = {}
    for name in DEPS:
        path = 'loader/src/external/' + name
        expected = git(source, 'ls-tree', 'HEAD', path).split()[2]
        if git(source / path, 'rev-parse', 'HEAD') != expected:
            raise RuntimeError('BuiltZygisk dependency drift: ' + name)
        subprocess.run(['git', '-C', str(source / path), 'diff', '--exit-code'], check=True)
        deps[name] = expected
    return source, deps

def stage(nova, receipt, verify=False):
    source, deps = inputs(nova)
    lock=(source/'zygiskd/Cargo.lock').read_bytes()
    recorded_lock=(receipt.parent/'BuiltZygisk.Cargo.lock').read_bytes()
    if lock!=recorded_lock:
        raise RuntimeError('BuiltZygisk Rust dependencies changed during the build')
    packages=tomllib.loads(lock.decode())['package']
    git_sources=sorted({p['source'] for p in packages if p.get('source','').startswith('git+')})
    if any(len(s.rsplit('#',1)[-1])!=40 for s in git_sources):
        raise RuntimeError('BuiltZygisk Rust git dependency lacks an immutable revision')
    target = nova / 'userspace/ksud/bin/aarch64'
    if verify:
        proof = json.loads(receipt.read_text())
        if (proof['source_pin'] != PIN or proof['dependencies'] != deps
                or proof['cargo_lock_sha256']!=sha(lock)):
            raise RuntimeError('BuiltZygisk source receipt mismatch')
        for name, digest in proof['assets_sha256'].items():
            if sha((target / name).read_bytes()) != digest:
                raise RuntimeError('Embedded BuiltZygisk asset changed: ' + name)
        return proof
    archives = list((source / 'module/build/outputs/release').glob('NyaZygisk-v*-release.zip'))
    if len(archives) != 1:
        raise RuntimeError('Expected one freshly built BuiltZygisk module')
    assets = {}
    with zipfile.ZipFile(archives[0]) as archive:
        if archive.testzip() is not None:
            raise RuntimeError('BuiltZygisk archive integrity failed')
        for name, (member, elfclass, machine) in FILES.items():
            data = archive.read(member)
            if not data:
                raise RuntimeError('Empty BuiltZygisk asset: ' + name)
            if elfclass is not None and (len(data) < 52 or data[:6] != b'\x7fELF' + bytes([elfclass, 1]) or int.from_bytes(data[18:20], 'little') != machine):
                raise RuntimeError('Wrong ELF architecture: ' + name)
            assets[name] = data
    assets['zygisk-sepolicy.rule'] = (source / 'module/src/sepolicy.rule').read_bytes()
    target.mkdir(parents=True, exist_ok=True)
    for name, data in assets.items():
        (target / name).write_bytes(data)
    proof = {'source_pin': PIN, 'source_repository': 'SukiSU-Nova/BuiltZygisk',
             'dependencies': deps, 'built_from_pinned_sources': True,
             'cargo_lock_sha256':sha(lock), 'rust_git_sources':git_sources,
             'rust_builds_enforced_locked':True,
             'archive_sha256': sha(archives[0].read_bytes()),
             'assets_sha256': {n: sha(d) for n, d in assets.items()},
             'device_runtime_tested': False, 'activation_changed': False}
    receipt.write_text(json.dumps(proof, indent=2) + '\n')
    return proof

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('nova', type=Path)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args()
    print(json.dumps(stage(args.nova, args.receipt, args.verify), indent=2))
