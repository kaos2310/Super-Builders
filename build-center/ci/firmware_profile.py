"""Install measured EZJ1 target data without changing the audited CRC baseline."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import shlex

DATA = Path(__file__).resolve().parent / 'firmware/ezj1'
PROFILE = 'S928BXXS6EZJ1-EUX-android14-6.1.162'
MARKER = '.build-center-firmware.json'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def crcs(text):
    result = {}
    for line in text.splitlines():
        if not line or line.startswith('#'):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        if re.fullmatch(r'0x[0-9a-fA-F]{8,16}', parts[0]):
            value, symbol = parts[:2]
        elif re.fullmatch(r'0x[0-9a-fA-F]{8,16}', parts[1]):
            symbol, value = parts[:2]
        else:
            continue
        value = value.lower()
        if symbol in result and result[symbol] != value:
            raise ValueError('Conflicting stock CRC: ' + symbol)
        result[symbol] = value
    return result


def load():
    profile = json.loads((DATA / 'profile.json').read_text())
    if profile['profile'] != PROFILE:
        raise ValueError('Unreviewed firmware profile')
    for name, expected in profile['files'].items():
        if Path(name).name != name or sha((DATA / name).read_bytes()) != expected:
            raise ValueError('Firmware evidence changed: ' + name)
    strict = crcs((DATA / 'strict-baseline.tsv').read_text())
    stock = crcs((DATA / 'stock-import-crcs.tsv').read_text())
    if len(strict) != 2485 or len(stock) != 5470 or any(stock.get(symbol) != value for symbol, value in strict.items()):
        raise ValueError('Supplied stock modules do not verify the strict Samsung baseline')
    values = {line.split('=', 1)[0]: shlex.split(line.split('=', 1)[1])[0]
              for line in (DATA / 'target.env').read_text().splitlines() if line and not line.startswith('#')}
    if values['SAMSUNG_TARGET_FIRMWARE'] != 'S928BXXS6EZJ1' or values['SAMSUNG_TARGET_CSC'] != 'EUX':
        raise ValueError('Wrong firmware identity')
    if values['SAMSUNG_TARGET_KERNEL_RELEASE'] != profile['kernel_release']:
        raise ValueError('Stock kernel release mismatch')
    return profile, values


def migrate(text, profile):
    for old, new in sorted(profile['migration'].items(), key=lambda pair: -len(pair[0])):
        text = text.replace(old, new)
    return text


def prepare_device_profile(path, values):
    document = json.loads(path.read_text(encoding='utf-8'))
    target = document['devices']['e3q']
    if target['firmware'] != 'S928BXXU6EZIF':
        raise ValueError('Unreviewed baseline device profile')
    evidence = json.loads((DATA / 'evidence.json').read_text())
    for key, source in {'firmware': 'FIRMWARE', 'firmware_package': 'PACKAGE',
                        'firmware_build_datetime': 'BUILD_DATETIME', 'ap': 'AP',
                        'csc_build': 'CSC_BUILD', 'cp': 'CP', 'csc': 'CSC'}.items():
        target[key] = values['SAMSUNG_TARGET_' + source]
    for key, archive in evidence['archives'].items():
        original = target['firmware_archives'][key]
        original.update({field: archive[field] for field in ('name', 'tar_md5', 'sha256', 'md5_verified')})
    target['stock_images'] = evidence['stock_images']
    version = values['SAMSUNG_TARGET_KERNEL_VERSION_STRING']
    target['stock_kernel'].update(
        release=values['SAMSUNG_TARGET_KERNEL_RELEASE'].removeprefix('6.1.162'),
        version_string=version, build_timestamp=version.removeprefix('#1 SMP PREEMPT '),
        build_user=values['SAMSUNG_TARGET_KERNEL_BUILD_USER'],
        build_host=values['SAMSUNG_TARGET_KERNEL_BUILD_HOST'],
        compiler_info=values['SAMSUNG_TARGET_KERNEL_COMPILER'])
    path.write_text(json.dumps(document, indent=2) + '\n', encoding='utf-8', newline='\n')


def prepare(root, plan):
    profile, values = load()
    if plan['profile'] != PROFILE:
        raise ValueError('Only the independently measured EZJ1 target is accepted')
    root = Path(root)
    marker = root / MARKER
    if marker.exists():
        return verify(root)
    android = root / 'android14-6.1'
    original = android / 'samsung-s928bxxu6ezif-target.env'
    if sha(original.read_text().encode()) != profile['baseline_target_sha256']:
        raise ValueError('Unreviewed baseline target file')
    baseline = android / 'samsung-e3q-zzi4-dlkm-crc-baseline.tsv'
    if sha(baseline.read_text().encode()) != profile['strict_baseline_sha256']:
        raise ValueError('The audited strict CRC baseline was changed')
    device_profile = root / 'device-profiles.json'
    prepare_device_profile(device_profile, values)
    helper = android / 'build-helpers'
    for path in helper.rglob('*'):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            before = path.read_text(encoding='utf-8')
        except UnicodeError:
            continue
        after = migrate(before, profile)
        if after != before:
            path.write_text(after, encoding='utf-8', newline='\n')
    for path in sorted(helper.rglob('*'), key=lambda p: len(p.parts), reverse=True):
        name = migrate(path.name, profile)
        if name != path.name:
            target = path.with_name(name)
            if target.exists():
                raise ValueError('Firmware helper rename collision: ' + str(target))
            path.rename(target)
    outputs = {
        'samsung-s928bxxs6ezj1-target.env': 'target.env',
        's928b-ezj1-firmware-evidence.json': 'evidence.json',
        'e3q-ezj1-gunyah-qcom-stock-modversions.tsv': 'gunyah-modversions.tsv',
    }
    for target, source in outputs.items():
        (android / target).write_bytes((DATA / source).read_bytes())
    receipt = {'profile': PROFILE, 'firmware': values['SAMSUNG_TARGET_FIRMWARE'], 'csc': 'EUX',
               'kernel_release': profile['kernel_release'], 'strict_baseline_sha256': profile['strict_baseline_sha256'],
               'strict_symbols_revalidated': 2485, 'stock_import_crcs_revalidated': 5470,
               'output_sha256': {name: sha((android / name).read_bytes()) for name in outputs},
               'device_profile_sha256': sha(device_profile.read_bytes()),
               'device_boot_tested': False, 'stock_archive_md5_verified': True}
    marker.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return verify(root)


def verify(root):
    profile, _ = load()
    root = Path(root)
    receipt = json.loads((root / MARKER).read_text())
    if receipt['profile'] != PROFILE or receipt['kernel_release'] != profile['kernel_release']:
        raise ValueError('Prepared firmware profile mismatch')
    if sha((root / 'device-profiles.json').read_bytes()) != receipt['device_profile_sha256']:
        raise ValueError('Prepared device profile drift')
    for name, expected in receipt['output_sha256'].items():
        if sha((root / 'android14-6.1' / name).read_bytes()) != expected:
            raise ValueError('Prepared firmware input drift: ' + name)
    if sha((root / 'android14-6.1/samsung-e3q-zzi4-dlkm-crc-baseline.tsv').read_text().encode()) != profile['strict_baseline_sha256']:
        raise ValueError('Strict CRC baseline drift')
    return receipt


def attest(root, image):
    receipt = verify(root)
    blob = Path(image).read_bytes()
    if len(blob) < 64 or blob[56:60] != b'ARM\x64':
        raise ValueError('Packaged kernel is not an uncompressed ARM64 Image')
    banner = b'Linux version ' + receipt['kernel_release'].encode() + b' '
    if banner not in blob:
        raise ValueError('Packaged Image does not identify the verified EZJ1 target')
    return dict(receipt, image_sha256=sha(blob), image_bytes=len(blob), device_boot_tested=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--image', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if bool(args.image) != bool(args.receipt):
        parser.error('--image and --receipt are required together')
    result = attest(args.root, args.image) if args.image else verify(args.root)
    if args.receipt:
        args.receipt.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
