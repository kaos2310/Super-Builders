"""Build ReSuSFS for the BakaSU EZJB kernel and its compiled SUSFS contract."""
from hashlib import sha256
import json
import zipfile

PIN = '7b65bde0710b5e7c6f755545cb15a4abd417f3a8'
SUSFS = 'f76b81f2a6bf98e4029cc0c823c054edbec29803'


def digest(data):
    return sha256(data).hexdigest()


def package(source, output, tools):
    if digest(source.read_bytes()) != '5fe9e0d35a06a498f0d2aad6549ce6d60cc7022887bd54cc82bc1530272ae421':
        raise ValueError('Unexpected reference ReSuSFS package')
    with zipfile.ZipFile(source) as archive:
        files = {name: (archive.getinfo(name), archive.read(name)) for name in archive.namelist()}
    manifest = json.loads(files['build-manifest.json'][1])
    proof = json.loads(files['SUSFS-TOOL-BUILD.json'][1])
    if (proof['pin'] != SUSFS or manifest['susfs_source_pin'] != SUSFS or
            proof['sha256'] != digest(files['bin/ksu_susfs'][1]) or
            manifest['runtime_helper_sha256'] != digest(files['bin/susfs-runtime'][1])):
        raise ValueError('ReSuSFS reference toolchain has drifted')

    def put(name, text):
        files[name] = (files[name][0], text.encode())

    for source_name, target_name in (('ksu_susfs', 'bin/ksu_susfs'), ('susfs-runtime', 'bin/susfs-runtime'),
                                     ('SUSFS-TOOL-BUILD.json', 'SUSFS-TOOL-BUILD.json')):
        files[target_name] = (files[target_name][0], (tools / source_name).read_bytes())

    installer = files['customize.sh'][1].decode()
    first_write = 'PERSISTENT_DIR=/data/adb/ReSuSFS'
    if installer.count(first_write) != 1:
        raise ValueError('Unexpected ReSuSFS installer seam')
    capability_check = '''[ "$BAKASU" = true ] && [ "$KSU_KERNEL_VER_CODE" = 35262 ] && [ "$KSU_UAPI_VER" = 6 ] || abort 'BakaSU 35262 / UAPI 6 required'
[ "$(uname -r)" = '6.1.162-android14-11-34343818-abS928BXXU6EZJB' ] || abort 'S928B EZJB kernel required'
[ "$version" = v2.4.0 ] || abort 'SUSFS v2.4.0 required'
features=$("$MODPATH/bin/ksu_susfs" show enabled_features 2>/dev/null) || abort 'SUSFS features query failed'
for feature in CONFIG_KSU_SUSFS_SUS_PATH CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER; do
    printf '%s\\n' "$features" | grep -qxF "$feature" || abort "Missing kernel feature: $feature"
done
runtime=$("$MODPATH/bin/susfs-runtime" status 2>/dev/null) || abort 'SUSFS Runtime-v1 query failed'
printf '%s\\n' "$runtime" | grep -q '"supported":15[,}]' || abort 'All four Runtime-v1 switches required'
'''
    put('customize.sh', installer.replace(first_write, capability_check + first_write))
    defaults = files['configs/config.txt'][1].decode()
    mount_hiding = '\nHIDE_SUS_MNTS_NON_SU=1\n'
    if defaults.count(mount_hiding) != 1:
        raise ValueError('Unexpected ReSuSFS mount-hiding default')
    put('configs/config.txt', defaults.replace(mount_hiding, '\nHIDE_SUS_MNTS_NON_SU=0\n'))
    put('module.prop', 'id=ReSuSFS\nname=ReSuSFS\n'
        'version=v26.10.23.susfs240.runtime1.bakasu35262.ezjb.r2\nversionCode=2026112103\n'
        'author=ahmed-alnassif; KAOSLAB integration\n'
        'description=BakaSU 35262 / SUSFS 2.4.0 for S928B EZJB.\n')
    # The Nova proof files document a different kernel pair.
    for name in tuple(files):
        if name.startswith('verification/') or name in ('LOCAL-DEVICE-READ-VERIFICATION.json', 'README-KAOSLAB-NOVA.md'):
            files.pop(name)
    current = {
        'module_id': 'ReSuSFS', 'official_release': manifest['official_release'],
        'profile': 'S928BXXU6EZJB-EUX', 'bakasu_version': 35262, 'bakasu_pin': PIN,
        'susfs_version': 'v2.4.0', 'susfs_pin': SUSFS, 'runtime_abi': 1,
        'reference_package_sha256': digest(source.read_bytes()),
        'susfs_tool_sha256': digest(files['bin/ksu_susfs'][1]), 'runtime_helper_sha256': digest(files['bin/susfs-runtime'][1]),
        'installer_checks_features': True, 'installer_mutates_runtime': False,
        'fresh_install_mount_hiding_default': False,
        'android_device_installation_tested': False,
    }
    put('build-manifest.json', json.dumps(current, indent=2) + '\n')
    sums = {name: digest(data) for name, (_, data) in sorted(files.items()) if name != 'SHA256SUMS'}
    put('SHA256SUMS', ''.join(f'{checksum}  {name}\n' for name, checksum in sums.items()))
    from packaging_io import write_zip
    write_zip(output, {name: value[1] for name, value in files.items()},
              {name: value[0] for name, value in files.items()})
