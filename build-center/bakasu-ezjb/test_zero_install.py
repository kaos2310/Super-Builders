"""Run Guard6's packaged installer against a fake Android environment."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile

with ZipFile(sys.argv[1]) as archive:
    installer = archive.read('customize.sh').decode()
    dispatcher = archive.read('bin/zm-brene76')
    assert b'"$KSUD" susfs' not in dispatcher
    for action in (b'show version', b'show enabled_features', b'add_open_redirect', b'add_sus_path_loop',
                   b'set_priority_uid_filter', b'add_sus_map'):
        assert b'"$SUSFS_TOOL" ' + action in dispatcher
    assert b'ZM_BAKASU1' in archive.read('bin/arm64-v8a/zm-native-core')

with tempfile.TemporaryDirectory(prefix='guard6-ezjb-') as temp:
    sandbox = Path(temp)
    state = sandbox / 'state'
    (state / 'emoji').mkdir(parents=True)
    (state / 'emoji/NotoColorEmoji.ttf').write_bytes(b'existing')
    config = state / 'config.toml'
    config.write_text('retained = true\n')
    module = sandbox / 'module'
    (module / 'bin').mkdir(parents=True)
    for name, body in {
        'ksu_susfs': '''[ "$*" = 'show version' ] || exit 95
printf '%s\\n' "$TEST_VERSION"''',
        'zm': '''[ "$ZM_BAKASU1" = true ] || exit 94
case "$*" in integrity) exit "$TEST_INTEGRITY";; 'susfs-compat --check') exit "$TEST_ABI";; *) exit 95;; esac''',
    }.items():
        file = module / 'bin' / name
        file.write_text('#!/bin/sh\n' + body + '\n')
        file.chmod(0o755)
    shell = '''
ui_print() { printf '%s\\n' "$*"; }
abort() { printf '%s\\n' "$*" >&2; exit 65; }
set_perm_recursive() { :; }
set_perm() { :; }
unzip() { :; }
uname() { case "$1" in -m) echo aarch64;; -r) echo "$TEST_RELEASE";; esac; }
'''
    source = shell + installer.replace('STATE=/data/adb/zeromount', f'STATE={state}')
    env = dict(os.environ, BAKASU='true', KSU='true', KSU_KERNEL_VER_CODE='35262', KSU_UAPI_VER='6',
               TEST_RELEASE='6.1.162-android14-11-34343818-abS928BXXU6EZJB',
               MODPATH=str(module), TEST_VERSION='v2.4.0', TEST_INTEGRITY='0', TEST_ABI='0')
    cases = [({}, 0, 'BakaSU 35262 / EZJB'), ({'BAKASU': 'false'}, 65, 'UAPI 6'),
             ({'KSU_KERNEL_VER_CODE': '35252'}, 65, '35262'), ({'TEST_RELEASE': 'other'}, 65, 'EZJB'),
             ({'TEST_VERSION': 'v2.3.0'}, 65, 'v2.4.0 required'),
             ({'TEST_INTEGRITY': '1'}, 65, 'Prüfsummen'), ({'TEST_ABI': '1'}, 65, 'ABI-Prüfung')]
    for overrides, code, expected in cases:
        result = subprocess.run(['sh', '-c', source], env=env | overrides, capture_output=True, text=True, timeout=5)
        assert result.returncode == code and expected in result.stdout + result.stderr, result
        assert config.read_text() == 'retained = true\n'
    print(f'PASS: {len(cases)} Guard6 installer cases with preserved settings')
