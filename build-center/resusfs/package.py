#!/usr/bin/env python3
"""Preserve ReSuSFS r2 and add the native SUS_PATH UID allowlist for Nova."""
from pathlib import Path
import argparse
import contextlib
import hashlib
import importlib.util
import io
import json
import re
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from ci.versions import official_nova_repository


def sha(data):
    return hashlib.sha256(data).hexdigest()


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Preserved module anchor changed: ' + old[:80])
    return text.replace(old, new, 1)


def package(helpers, plan, runtime_helper, susfs_tool, output):
    """Reuse the audited original-UI r2 builder, then apply the reviewed addon."""
    code = plan['sukisu_code']
    if (not official_nova_repository(plan)
            or plan.get('sukisu_family') != 'nova'
            or code != 30000 + plan['sukisu_count'] + 996):
        raise ValueError('Nova identity/version mapping is not confirmed')
    if any(not re.fullmatch('[0-9a-f]{40}', plan[key]) for key in ('sukisu_commit', 'susfs_commit')):
        raise ValueError('Immutable full source pins required')
    if plan.get('susfs_version') != 'v2.4.0':
        raise ValueError('This preserved ReSuSFS adapter requires reviewed SUSFS v2.4.0')
    legacy_path = helpers / f'resusfs-{code}-240'
    source = json.loads((legacy_path / 'SOURCE.json').read_text())
    if source['pin'] != plan['susfs_commit']:
        raise ValueError('ReSuSFS helper and kernel plan use different SUSFS sources')
    # Require the actual refreshed official parser, not a version label on old CLI.
    contract_files = ('main.c', 'features/sus_path_uid_filter.c')
    for name in contract_files:
        data = (legacy_path / 'upstream' / name).read_bytes()
        if sha(data) != source['source_files_sha256'].get(name):
            raise ValueError('Native UID filter source proof mismatch: ' + name)
        if b'set_sus_path_uid_filter' not in data:
            raise ValueError('Official native UID filter implementation is missing: ' + name)
    native_source = (legacy_path / 'upstream/features/sus_path_uid_filter.c').read_text()
    for anchor in ('#define CMD_SUSFS_SET_SUS_PATH_UID_FILTER 0x55554',
                   'syscall(SYS_reboot, KSU_INSTALL_MAGIC1, SUSFS_MAGIC, CMD_SUSFS_SET_SUS_PATH_UID_FILTER, &info)',
                   'return info.err;'):
        if anchor not in native_source:
            raise ValueError('Official native UID filter ABI changed; review the adapter')
    if b'set_sus_path_uid_filter' not in susfs_tool.read_bytes():
        raise ValueError('Source-built CLI does not contain the new native command')
    spec = importlib.util.spec_from_file_location('resusfs_preserved_r2', legacy_path / 'package.py')
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    output.mkdir(parents=True, exist_ok=True)
    # Keep intermediate r2 outside the artifact tree: publication requires one ZIP.
    with tempfile.TemporaryDirectory(prefix='.resusfs-r2-', dir=output.parent) as temp:
        intermediate = Path(temp)
        if not intermediate.resolve().is_relative_to(output.parent.resolve()):
            raise ValueError('Temporary package path escaped output parent')
        with contextlib.redirect_stdout(io.StringIO()):
            prior = legacy.package(runtime_helper, susfs_tool, intermediate)
        with zipfile.ZipFile(intermediate / prior['zip_name']) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
    before = dict(files)
    new_design = plan.get('module_design') == 'zeromount-3d'
    files.pop('SHA256SUMS')
    files['bin/resusfs-path-filter'] = (HERE / 'resusfs-path-filter').read_bytes()
    files['webroot/assets/resusfs-path-filter.mjs'] = (HERE / 'resusfs-path-filter.mjs').read_bytes()
    html = files['webroot/index.html'].decode()
    html = once(html, '</head>', '  <script type="module" src="./assets/resusfs-path-filter.mjs?r=3"></script>\n</head>')
    if new_design:
        style = (HERE / 'resusfs-3d.css').read_bytes()
        files['webroot/assets/resusfs-3d.css'] = style
        html = once(html, '</head>', '  <link rel="stylesheet" href="./assets/resusfs-3d.css">\n</head>')
    files['webroot/index.html'] = html.encode()
    boot = files['boot-completed.sh'].decode()
    boot = once(boot, 'sh "$MODDIR/bin/resusfs-control" restore priority',
                'sh "$MODDIR/bin/resusfs-control" restore priority\n'
                'sh "$MODDIR/bin/resusfs-path-filter" restore')
    files['boot-completed.sh'] = boot.encode()
    version_suffix = '.3d' if new_design else ''
    version_code = 2026112601 if new_design else 2026112001
    files['module.prop'] = (
        'id=ReSuSFS\nname=ReSuSFS\n'
        f'version=v26.10.23.kaoslab.susfs240.runtime1.r3.nova{code}{version_suffix}\n'
        f'versionCode={version_code}\n'
        'author=ahmed-alnassif; KAOSLAB integration\n'
        'description=Original ReSuSFS + optional Runtime, Priority UID and native SUS_PATH UID allowlist; Nova source pair.\n'
    ).encode()
    files['README-KAOSLAB-NOVA.md'] = (HERE / 'README.md').read_bytes()
    manifest = json.loads(files['build-manifest.json'])
    manifest.update({
        'revision': 'r3', 'sukisu_family': 'nova', 'sukisu_repository': plan['sukisu_repository'],
        'sukisu_code': code, 'sukisu_count': plan['sukisu_count'],
        'sukisu_source_pin': plan['sukisu_commit'], 'susfs_source_pin': plan['susfs_commit'],
        'target_profile': plan.get('profile', plan.get('target_profile')),
        'original_ui_preserved': True, 'runtime_ui_is_separate_addition': True,
        'existing_config_overwritten': False, 'owner_transferred': False,
        'global_cli_replaced': False, 'device_installation_tested': False,
        'nova_code_reset_does_not_reset_user_config': True,
        'r3_packager_sources_sha256': {
            name: sha((HERE / name).read_bytes())
            for name in ('package.py', 'resusfs-path-filter', 'resusfs-path-filter.mjs', 'README.md')
        },
        'sus_path_uid_filter': {
            'command': 'set_sus_path_uid_filter', 'kernel_command_hex': '0x55554',
            'semantics': 'selected_app_uids_can_see_sus_path_paths',
            'source_pin': source['pin'], 'source_file_sha256': {
                name: source['source_files_sha256'][name] for name in contract_files
            }, 'kernel_readback_available': False, 'status_issues_mutation': False,
            'native_support_probed_on_read': False, 'setter_error_never_saves_selection': True,
            'persistent_file': '/data/adb/ReSuSFS/sus-path-visible-packages',
            'default_selection': 'absent_no_boot_setter', 'empty_selection_cli_argument': ',',
            'revision_compare_and_swap': True, 'device_setter_tested': False,
        },
    })
    if new_design:
        manifest.update(module_design=plan['module_design'], module_design_sha256=sha(style),
                        sukisu_repository_url=plan['sukisu_repository_url'])
    allowed_changes = {'webroot/index.html', 'boot-completed.sh', 'module.prop', 'build-manifest.json'}
    changed_existing = {name for name, data in before.items() if name != 'SHA256SUMS' and files.get(name) != data}
    if changed_existing - allowed_changes:
        raise ValueError('An unreviewed existing r2 file changed: ' + str(changed_existing))
    manifest['preserved_r2_files_sha256'] = {
        name: sha(data) for name, data in before.items()
        if name != 'build-manifest.json' and files.get(name) == data
    }
    manifest['r3_changed_existing_r2_files'] = sorted(changed_existing | {'build-manifest.json'})
    manifest['r3_added_files'] = sorted(set(files) - set(before))
    with zipfile.ZipFile(legacy_path / 'module-base.zip') as archive:
        original = {item.filename: archive.read(item) for item in archive.infolist() if not item.is_dir()}
    # Manifest excludes itself from its recursive file maps. SHA256SUMS covers it.
    manifest['unchanged_files_sha256'] = {name: sha(data) for name, data in original.items() if files.get(name) == data}
    manifest['changed_files_sha256'] = {
        name: sha(data) for name, data in files.items()
        if name != 'build-manifest.json' and original.get(name) != data
    }
    files['build-manifest.json'] = (json.dumps(manifest, indent=2) + '\n').encode()
    files['SHA256SUMS'] = ''.join(sha(data) + '  ' + name + '\n' for name, data in sorted(files.items())).encode()
    design_suffix = '-3D' if new_design else ''
    name = f'ReSuSFS-v26.10.23-KAOSLAB-SUSFS2.4.0-Runtime1-r3-Nova{code}{design_suffix}-arm64.zip'
    target = output / name
    with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for member, data in sorted(files.items()):
            info = zipfile.ZipInfo(member, (2026, 11, 20, 0, 0, 0))
            info.create_system = 3
            mode = 0o100755 if member.startswith('bin/') or member.endswith('.sh') or member.endswith('update-binary') else 0o100644
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    with zipfile.ZipFile(target) as archive:
        if archive.testzip() is not None:
            raise ValueError('Final ReSuSFS archive CRC failure')
        for line in archive.read('SHA256SUMS').decode().splitlines():
            digest, member = line.split('  ', 1)
            if sha(archive.read(member)) != digest:
                raise ValueError('Final member checksum mismatch: ' + member)
    result = dict(manifest, zip_name=name, zip_sha256=sha(target.read_bytes()), bytes=target.stat().st_size,
                  crc_and_all_member_checksums_passed=True)
    (output / 'PACKAGE-VERIFICATION.json').write_text(json.dumps(result, indent=2) + '\n')
    (output / 'SHA256SUMS').write_text(result['zip_sha256'] + '  ' + name + '\n')
    print(json.dumps({key: value for key, value in result.items() if not isinstance(value, dict)}, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--helpers', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--runtime-helper', type=Path, required=True)
    parser.add_argument('--susfs-tool', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    package(args.helpers, json.loads(args.plan.read_text()), args.runtime_helper, args.susfs_tool, args.output)
