#!/usr/bin/env python3
"""Verify the pinned Rust source, host libclang and generated ARM64 binaries."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--version', required=True, type=int)
    parser.add_argument('--receipt', required=True, type=Path)
    parser.add_argument('--verify-build', action='store_true')
    args = parser.parse_args()
    source = args.source.resolve()
    if not re.fullmatch(r'[0-9a-f]{40}', args.commit):
        raise RuntimeError('A full immutable source commit is required')
    if run('git', '-C', str(source), 'rev-parse', 'HEAD') != args.commit:
        raise RuntimeError('ReSukiSU checkout differs from the requested pin')
    count = int(run('git', '-C', str(source), 'rev-list', '--count', 'HEAD'))
    if 30700 + count != args.version:
        raise RuntimeError('ReSukiSU version formula mismatch')

    rust = run('rustc', '+nightly', '--version', '--verbose')
    release = re.search(r'^release: (\d+)\.(\d+)\.(\d+)(.*)$', rust, re.M)
    # Edition 2024 raises the effective minimum above bindgen's Rust 1.71 floor.
    if not release or tuple(map(int, release.group(1, 2, 3))) < (1, 85, 0) or 'nightly' not in release[4]:
        raise RuntimeError('Rust Nightly >= 1.85 is required for Edition 2024')
    cargo = run('cargo', '+nightly', '--version')
    locked = {}
    for crate in ('ksud', 'ksuinit'):
        for filename in ('Cargo.toml', 'Cargo.lock'):
            relative = f'userspace/{crate}/{filename}'
            data = (source / relative).read_bytes()
            upstream = subprocess.check_output(['git', '-C', str(source), 'show', f'{args.commit}:{relative}'])
            if data != upstream:
                raise RuntimeError(f'{relative} differs from the pinned upstream file')
            locked[relative] = digest(data)
    lock = tomllib.loads((source / 'userspace/ksud/Cargo.lock').read_text())
    bindgen = [p['version'] for p in lock['package'] if p['name'] == 'bindgen']
    if bindgen != ['0.73.1']:
        raise RuntimeError(f'Expected locked bindgen 0.73.1, got {bindgen}')

    clang = run(os.environ['CLANG_PATH'], '--version')
    libpath = Path(os.environ['LIBCLANG_PATH']) / 'libclang.so'
    lib = ctypes.CDLL(str(libpath))
    lib.clang_createIndex.argtypes = [ctypes.c_int, ctypes.c_int]
    lib.clang_createIndex.restype = ctypes.c_void_p
    lib.clang_disposeIndex.argtypes = [ctypes.c_void_p]
    index = lib.clang_createIndex(0, 0)
    if not index:
        raise RuntimeError('libclang could not create a Clang index')
    lib.clang_disposeIndex(index)
    receipt = dict(commit=args.commit, version=args.version, commit_count=count,
                   rustc=rust, cargo=cargo, clang=clang, libclang=str(libpath.resolve()),
                   locked_source_sha256=locked, bindgen='0.73.1', target='aarch64-linux-android',
                   runtime_test='not performed', build_verified=False)
    if args.verify_build:
        previous = json.loads(args.receipt.read_text())
        for key in ('commit', 'version', 'locked_source_sha256', 'rustc', 'cargo'):
            if previous[key] != receipt[key]:
                raise RuntimeError(f'Build inputs changed: {key}')
        outputs = {}
        for crate in ('ksud', 'ksuinit'):
            path = source / f'userspace/{crate}/target/aarch64-linux-android/release/{crate}'
            data = path.read_bytes()
            if len(data) < 64 or data[:6] != b'\x7fELF\x02\x01' or int.from_bytes(data[18:20], 'little') != 183:
                raise RuntimeError(f'{crate} is not an ELF64 little-endian AArch64 binary')
            outputs[crate] = dict(sha256=digest(data), size=len(data))
        build_dir = source / 'userspace/ksud/target/aarch64-linux-android/release/build'
        versions = [p.read_text().strip() for p in build_dir.glob('ksud-*/out/VERSION_CODE')]
        if versions != [str(args.version)]:
            raise RuntimeError(f'ksud generated version mismatch: {versions}')
        bindings = list(build_dir.glob('ksud-*/out/bindings.rs'))
        if len(bindings) != 1 or bindings[0].stat().st_size == 0:
            raise RuntimeError('bindgen did not produce exactly one nonempty UAPI binding file')
        receipt.update(build_verified=True, binaries=outputs, bindings_sha256=digest(bindings[0].read_bytes()),
                       ndk=os.environ['ANDROID_NDK_HOME'])
    args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
