"""Port the pinned Guard6 module to the BakaSU EZJB installer and SUSFS CLI."""
import json
from zipfile import ZipFile

from patch_zeromount import ADAPTER, CHECKSUMS, NATIVE, REFERENCE_SHA, digest, patch_adapter, replace_once

BAKA_MARKER = b'''[ "${BAKASU:-}" = true ] && export ZM_BAKASU1=true
'''


def package(source, output, tools):
    if digest(source.read_bytes()) != REFERENCE_SHA:
        raise ValueError('Unrecognized Guard6 input')
    with ZipFile(source) as archive:
        entries = {item.filename: item for item in archive.infolist()}
        members = {name: archive.read(name) for name in entries}

    def edit(name, before, after):
        members[name] = replace_once(members[name], before, after)

    # Single fixed-width data literal used by this exact native binary's
    # integrated SUSFS detector. Its executable instructions are unchanged.
    core = members[NATIVE]
    token = b'KSU_SUKISU'
    if (digest(core) != '2144cf2f40f3f8a5dd41e848a56047598cc6307165a6ae084107bd6f833b3d91'
            or core.count(token) != 1 or core.index(token) != 528316):
        raise ValueError('Guard6 detector input changed')
    members[NATIVE] = core.replace(token, b'ZM_BAKASU1', 1)
    if [index for index, (a, b) in enumerate(zip(core, members[NATIVE])) if a != b] != list(range(528316, 528326)):
        raise ValueError('Unexpected native detector change')
    members[ADAPTER] = patch_adapter(members[ADAPTER])
    for name in ('bin/zm', ADAPTER):
        edit(name, b'#!/system/bin/sh\n', b'#!/system/bin/sh\n' + BAKA_MARKER)
    start = members['bin/zm'].index(b"    _ksud=''\n")
    end = members['bin/zm'].index(b'    _features=$(printf', start)
    members['bin/zm'] = members['bin/zm'][:start] + (
        b'    _features=$("$BINDIR/ksu_susfs" show enabled_features 2>/dev/null) || return 1\n'
    ) + members['bin/zm'][end:]
    data = members[ADAPTER]
    start, end = data.index(b'KSUD='), data.index(b'STATE=')
    data = data[:start] + data[end:]
    mappings = {'version': 'show version', 'features': 'show enabled_features',
                'add-open-redirect': 'add_open_redirect', 'add-sus-path-loop': 'add_sus_path_loop',
                'set-priority-uid-filter': 'set_priority_uid_filter', 'add-sus-map': 'add_sus_map'}
    for source_cmd, private_cmd in mappings.items():
        old = f'"$KSUD" susfs {source_cmd}'.encode()
        if old not in data:
            raise ValueError(f'Missing legacy ABI command {source_cmd}')
        data = data.replace(old, f'"$SUSFS_TOOL" {private_cmd}'.encode())
    if b'"$KSUD"' in data:
        raise ValueError('Unmapped legacy CLI command')
    members[ADAPTER] = data

    installer = members['customize.sh']
    start = installer.index(b'[ "$KSU"')
    end = installer.index(b'unzip -o', start)
    gate = b'''[ "$KSU" = true ] && [ "$BAKASU" = true ] && [ "$KSU_KERNEL_VER_CODE" = 35262 ] && [ "$KSU_UAPI_VER" = 6 ] || abort "BakaSU 35262 / UAPI 6 required"
[ "$(uname -m)" = aarch64 ] || abort "ARM64 required"
[ "$(uname -r)" = '6.1.162-android14-11-34343818-abS928BXXU6EZJB' ] || abort "S928B EZJB kernel required"
export ZM_BAKASU1=true
'''
    members['customize.sh'] = installer[:start] + gate + installer[end:]
    start = b'"$MODPATH/bin/zm" integrity'
    edit('customize.sh', start, b'''set_perm "$MODPATH/ksu_susfs" 0 0 0755
VERSION=$("$MODPATH/bin/ksu_susfs" show version 2>/dev/null) || abort "SUSFS version query failed"
[ "$VERSION" = v2.4.0 ] || abort "SUSFS v2.4.0 required"
''' + start)
    edit('customize.sh', b'SukiSU Nova35004', b'BakaSU 35262 / EZJB')
    members['ksu_susfs'] = b'#!/system/bin/sh\nexec "${0%/*}/bin/ksu_susfs" "$@"\n'
    edit('module.prop', b'sukisunova35004.runtime-addon1\nversionCode=2026112001',
         b'bakasu35262.ezjb.propwatchfix1\nversionCode=2026112102')
    edit('module.prop', b'SukiSU Nova35004 / S928BXXS6EZJ1', b'BakaSU 35262 / S928BXXU6EZJB')
    members['bin/ksu_susfs'] = (tools / 'ksu_susfs').read_bytes()
    members['bin/susfs-runtime'] = (tools / 'susfs-runtime').read_bytes()
    members['SUSFS-TOOL-BUILD.json'] = (tools / 'SUSFS-TOOL-BUILD.json').read_bytes()
    for name in ('README-Guard6.13-Nova35004.md',):
        members.pop(name)
    for name in ('BRENE76-INTEGRATION.json', 'build-manifest.json'):
        members['reference/' + name] = members.pop(name)
    manifest = {
        'kernel': 'BakaSU 35262', 'firmware': 'S928BXXU6EZJB', 'susfs': 'v2.4.0',
        'reference_zip_sha256': REFERENCE_SHA, 'native_core_reference_sha256': digest(core),
        'native_core_sha256': digest(members[NATIVE]), 'native_detector_marker_offset': 528316,
        'prop_watch_target': NATIVE, 'prop_watch_adapter_sha256': digest(members[ADAPTER]),
        'device_tested': False,
    }
    members['build-manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    for name in CHECKSUMS:
        members.pop(name)
    mutable = {'module.prop', 'customize.sh', 'webroot/cache.json', 'webroot/zm-init.js'}
    for name in CHECKSUMS:
        members[name] = ''.join(f'{digest(raw)}  {member}\n' for member, raw in sorted(members.items())
                                if member not in CHECKSUMS and (name == 'SHA256SUMS' or member not in mutable)).encode()
    from packaging_io import write_zip
    write_zip(output, members, entries)
