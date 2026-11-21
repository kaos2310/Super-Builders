"""Build and verify the three matching Super-Builders EZJB release ZIPs."""
import argparse
import json
from pathlib import Path, PurePosixPath
import subprocess
from zipfile import ZipFile

import pack_resusfs
import pack_zero
from packaging_io import digest, write_zip

HERE = Path(__file__).resolve().parent
KERNEL = '6.1.162-BakaSU-35262-SUSFS2.4.0-S928BXXU6EZJB-EUX-Strict-AnyKernel3.zip'
ZERO = 'ZeroMount-Guard6.13-BRENE76-BakaSU35262-SUSFS2.4.0-EZJB-arm64.zip'
RESUSFS = 'ReSuSFS-v26.10.23-BakaSU35262-SUSFS2.4.0-EZJB-arm64.zip'


def build_tools(source, clang, output):
    output.mkdir(parents=True, exist_ok=True)
    with ZipFile(source) as archive:
        receipt = json.loads(archive.read('SUSFS-TOOL-BUILD.json'))
        if receipt['pin'] != 'f76b81f2a6bf98e4029cc0c823c054edbec29803':
            raise ValueError('Unexpected SuSFS CLI source pin')
        for name, expected in receipt['source_files_sha256'].items():
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe SuSFS CLI source path')
            data = archive.read('source/ksu_susfs/' + name)
            if digest(data) != expected:
                raise ValueError('SuSFS CLI source checksum mismatch')
            destination = output / 'source' / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
    source_dir = output / 'source'
    sources = sorted(source_dir.glob('*.c')) + sorted((source_dir / 'features').glob('*.c'))
    common = [str(clang), '--target=aarch64-linux-android26', '-Wl,-z,max-page-size=16384']
    cli = output / 'ksu_susfs'
    subprocess.run([*common, '-O3', '-fstack-protector-strong', '-D_FORTIFY_SOURCE=2', '-flto=thin',
                    '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', '-I'+str(source_dir/'includes'),
                    *map(str, sources), '-o', str(cli)], check=True)
    runtime = output / 'susfs-runtime'
    subprocess.run([*common, '-Os', '-nostdlib', '-static', '-fno-builtin', '-fno-stack-protector',
                    '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '-Wl,-e,_start,--build-id=none',
                    str(HERE / 'susfs-runtime.c'), '-o', str(runtime)], check=True)
    for binary in (cli, runtime):
        header = binary.read_bytes()[:20]
        if header[:6] != b'\x7fELF\x02\x01' or header[18:20] != b'\xb7\x00':
            raise ValueError('Expected Android ARM64 CLI and runtime helper')
    receipt.update(sha256=digest(cli.read_bytes()), bytes=cli.stat().st_size,
                   compiler=subprocess.check_output([clang, '--version'], text=True).splitlines()[0],
                   source_file_count=len(sources), built_from_official_c_sources=True,
                   device_installation_tested=False)
    (output / 'SUSFS-TOOL-BUILD.json').write_text(json.dumps(receipt, indent=2) + '\n')


def pack_kernel(source, work, output):
    if digest(source.read_bytes()) != '5ef1132b7b8a2abc27fcc1cc041afe766dc5567f742e0c0f65ee8997e496e2ef':
        raise ValueError('Unexpected AnyKernel3 reference template')
    verification = (HERE / 'kernel-build-verification.json').read_bytes()
    proof = json.loads(verification)
    image = (work / 'out/arch/arm64/boot/Image').read_bytes()
    if (proof['image_sha256'] != digest(image) or not proof['strict_passed'] or not proof['thinlto_present']
            or proof['native_kpm_present'] or proof['missing_required_functions']):
        raise ValueError('AnyKernel3 requires the verified BakaSU EZJB Image')
    with ZipFile(source) as archive:
        entries = {item.filename: item for item in archive.infolist() if not item.is_dir() and (
            item.filename.startswith(('META-INF/', 'tools/')) or item.filename in ('banner', 'anykernel.sh', 'LICENSE'))}
        members = {name: archive.read(name) for name in entries}
    script = members['anykernel.sh']
    if script.count(b'S928BXXS6EZJ1') != 3 or script.count(b'block=boot\n') != 1:
        raise ValueError('AnyKernel3 firmware or partition anchor changed')
    members['anykernel.sh'] = script.replace(b'S928BXXS6EZJ1', b'S928BXXU6EZJB').replace(
        b'kernel.string=Wild Kernels by TheWildJames aka Morgan Weedman',
        b'kernel.string=Super-Builders BakaSU 35262 / SUSFS 2.4.0 / EZJB', 1)
    members.update({
        'Image': image, 'BUILD-CONFIG.txt': (work/'out/.config').read_bytes(),
        'FIRMWARE-TARGET.json': (HERE/'EZJB-STOCK-VERIFICATION.json').read_bytes(),
        'BUILD-VERIFICATION.json': verification, 'STRICT-KMI.txt': (work/'strict-audit/summary.md').read_bytes(),
    })
    members['SHA256SUMS'] = ''.join(f'{digest(raw)}  {name}\n' for name, raw in sorted(members.items())).encode()
    write_zip(output / KERNEL, members, entries)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('stage', choices=('kernel', 'modules'))
    ap.add_argument('inputs', type=Path)
    ap.add_argument('work', type=Path)
    ap.add_argument('output', type=Path)
    ap.add_argument('--clang', type=Path)
    a = ap.parse_args()
    if a.stage == 'kernel':
        pack_kernel(a.inputs / 'kernel.zip', a.work, a.output)
    else:
        build_tools(a.inputs / 'resusfs.zip', a.clang, a.work)
        pack_zero.package(a.inputs / 'zeromount.zip', a.output / ZERO, a.work)
        pack_resusfs.package(a.inputs / 'resusfs.zip', a.output / RESUSFS, a.work)
