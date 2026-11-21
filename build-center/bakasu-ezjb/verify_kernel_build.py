"""Compare the actual EZJB build outputs with the validated Samsung KMI table."""
from base64 import b64decode
from hashlib import sha256
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT.parent / 'ci/firmware/ezj1'
REQUIRED = ('USER_NS', 'PID_NS', 'CGROUPS', 'KSU', 'KSU_SUSFS', 'KSU_SUSFS_SUS_PATH',
            'KSU_SUSFS_OPEN_REDIRECT', 'KSU_SUSFS_PRIORITY_UID_FILTER', 'KSU_SUSFS_UID_GATED_HIDING',
            'KSU_SUSFS_HIDDEN_NAME', 'KSU_SUSFS_UNICODE_FILTER', 'KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS',
            'MODVERSIONS', 'ZEROMOUNT')
FEATURES = ('susfs_set_sus_path_uid_filter', 'susfs_set_priority_uid_filter',
            'susfs_runtime_handle', 'susfs_runtime_enabled', 'susfs_is_hidden_name')
SAMSUNG_GKI_CERT_SHA256 = 'f1efe8cfd3717fdd6d9fb3667b856600c718fa1250b4081347732e43a8bbceba'


def verify_radio_module_trust(out, image, config):
    required = {
        'CONFIG_MODULE_SIG=y', 'CONFIG_MODULE_SIG_PROTECT=y', 'CONFIG_MODULE_SIG_ALL=y',
        'CONFIG_SYSTEM_TRUSTED_KEYRING=y', 'CONFIG_RFKILL=m',
        'CONFIG_SYSTEM_TRUSTED_KEYS="certs/samsung-ezjb-gki.pem"',
    }
    if required - config:
        raise ValueError(f'Unexpected EZJB module signing config: {sorted(required - config)}')
    pem = (ROOT / 'samsung-ezjb-gki.pem').read_bytes().splitlines()
    if pem[0] != b'-----BEGIN CERTIFICATE-----' or pem[-1] != b'-----END CERTIFICATE-----':
        raise ValueError('Expected the public Samsung GKI certificate')
    der = b64decode(b''.join(pem[1:-1]), validate=True)
    trusted = (out / 'certs/x509_certificate_list').read_bytes()
    if sha256(der).hexdigest() != SAMSUNG_GKI_CERT_SHA256 or der not in trusted or der not in image:
        raise ValueError('The Samsung EZJB trust anchor is missing from the built Image')
    # These adjacent fixed-width entries belong to the protected export table.
    rfkill_export_proof = b'rfkill_alloc'.ljust(39, b'\0') + b'rfkill_blocked\0'
    if rfkill_export_proof not in image:
        raise ValueError('The compiled GKI export protection for rfkill is missing')
    return {'samsung_gki_certificate_sha256': SAMSUNG_GKI_CERT_SHA256,
            'certificate_linked_in_trusted_key_list': True, 'rfkill_export_protection_retained': True}


def main(out):
    strict = {}
    for line in (REFERENCE / 'strict-baseline.tsv').read_text().splitlines():
        if line and not line.startswith('#'):
            symbol, expected, previous, _ = line.split('\t')
            if expected != previous or symbol in strict:
                raise ValueError(f'Inconsistent strict baseline for {symbol}')
            strict[symbol] = expected.lower()
    if len(strict) != 2485:
        raise ValueError('Expected full set of 2485 target CRCs')
    crcs, providers = {}, {}
    for line in (out / 'Module.symvers').read_text().splitlines():
        crc, symbol, provider, *_ = line.split('\t')
        crcs.setdefault(symbol, set()).add(crc.lower())
        providers.setdefault(symbol, set()).add(provider)
    missing = sorted(set(strict).difference(crcs))
    mismatch = {symbol: [strict[symbol], sorted(crcs[symbol])] for symbol in sorted(set(strict).intersection(crcs))
                if crcs[symbol] != {strict[symbol]}}
    image = (out / 'arch/arm64/boot/Image').read_bytes()
    if image.count(b'IKCFG_ST') != 1:
        raise ValueError('Unique kernel configuration marker is required')
    start = image.index(b'IKCFG_ST') + 8
    end = image.index(b'IKCFG_ED', start)
    config = set(gzip.decompress(image[start:end]).decode().splitlines())
    radio_module_trust = verify_radio_module_trust(out, image, config)
    reference = json.loads((ROOT / 'DROIDSPACES-CONFIG.json').read_text())
    droidspaces = {name for name, value in reference['expected_config'].items() if value == 'y'}
    for group in reference['verified_runtime_prerequisites'].values():
        droidspaces.update(group)
    required = set(REQUIRED) | droidspaces | {'EROFS_FS_ZIP_LZMA', 'XZ_DEC_MICROLZMA', 'GUNYAH'}
    absent = sorted(name for name in required if f'CONFIG_{name}=y' not in config)
    enabled_limits = [name for name in ('CGROUP_PIDS', 'CFS_BANDWIDTH') if f'CONFIG_{name}=y' in config]
    linked = {line.split()[-1].split('.llvm.')[0] for line in (out / 'System.map').read_text().splitlines() if line}
    missing_functions = sorted(set(FEATURES).difference(linked))
    identity = (b'Linux version 6.1.162-android14-11-34343818-abS928BXXU6EZJB' in image
                and b'Mon Oct 19 08:59:36 UTC 2026' in image and b'v2.4.0' in image
                and b'v4.2.0-rc3-7b65bde0' in image)
    result = {
        'kernel_linked': True, 'image_sha256': sha256(image).hexdigest(), 'target_identity_in_image': identity,
        'strict_symbol_count': len(strict), 'strict_missing': missing, 'strict_mismatch': mismatch,
        'strict_symbols_only_in_gki_modules': sum('vmlinux' not in providers[symbol] for symbol in strict.keys() & providers.keys()),
        'strict_passed': not missing and not mismatch, 'missing_expected_options': absent,
        'enabled_cpu_pid_limits': enabled_limits, 'missing_required_functions': missing_functions,
        'package_uid_refresh_linked': 'susfs_refresh_after_package_rename' in linked,
        'thinlto_present': 'CONFIG_LTO_CLANG_THIN=y' in config,
        'native_kpm_present': 'CONFIG_KPM=y' in config, 'android_device_tested': False,
        'radio_module_trust': radio_module_trust,
    }
    (ROOT / 'kernel-build-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: (len(v) if k in ('strict_missing', 'strict_mismatch') else v)
                      for k, v in result.items()}, indent=2))
    if (missing or mismatch or absent or enabled_limits or missing_functions or not identity
            or not result['thinlto_present'] or not result['package_uid_refresh_linked'] or result['native_kpm_present']):
        raise SystemExit(1)


if __name__ == '__main__':
    main(Path(sys.argv[1]))
