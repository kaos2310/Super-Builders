"""Test candidate installation against isolated successful and rejected inputs."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

with zipfile.ZipFile(sys.argv[1]) as archive:
    installer = archive.read('customize.sh').decode()
    defaults = archive.read('configs/config.txt').splitlines()
    assert [line for line in defaults if line.startswith(b'HIDE_SUS_MNTS_NON_SU=')] == [b'HIDE_SUS_MNTS_NON_SU=0']

with tempfile.TemporaryDirectory(prefix='resusfs-baka-') as directory:
    root = Path(directory)
    commands = root / 'bin'
    commands.mkdir()
    module = root / 'module'
    tools = module / 'bin'
    tools.mkdir(parents=True)
    persistent = root / 'state'
    persistent.mkdir()
    state = persistent / 'previous-settings'
    state.write_text('existing profile\n')

    def mock(path, body):
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o755)

    mock(commands / 'getprop', 'echo arm64-v8a')
    mock(commands / 'uname', 'echo "$TEST_RELEASE"')
    mock(tools / 'ksu_susfs', '''case "$2" in
version) echo "$TEST_VERSION";;
enabled_features) printf '%s\\n' CONFIG_KSU_SUSFS_SUS_PATH "$TEST_PRIORITY";;
*) exit 90;;
esac''')
    mock(tools / 'susfs-runtime', '[ "$*" = status ] || exit 93; printf \'{"supported":%s}\\n\' "$TEST_RUNTIME"')
    fixture = installer.replace('/data/adb/ReSuSFS', str(persistent))
    functions = '''
ui_print() { printf '%s\\n' "$*"; }
abort() { printf '%s\\n' "$*" >&2; exit 65; }
set_perm_recursive() { :; }
set_perm() { :; }
'''
    env = dict(os.environ, BAKASU='true', KSU='true', KSU_KERNEL_VER_CODE='35285', KSU_UAPI_VER='6',
               MODPATH=str(module), PATH=f'{commands}:/usr/bin:/bin', TEST_VERSION='v2.4.0',
               TEST_RELEASE='6.1.162-android14-11-34343818-abS928BXXU6EZJB',
               TEST_RUNTIME='15', TEST_PRIORITY='CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER')
    cases = [({}, 0, 'existing configuration retained'), ({'BAKASU': 'false'}, 65, 'BakaSU 35285'),
             ({'KSU_UAPI_VER': '5'}, 65, 'UAPI 6'), ({'KSU_KERNEL_VER_CODE': '35262'}, 65, '35285'),
             ({'TEST_RELEASE': 'other-release'}, 65, 'EZJB'), ({'TEST_VERSION': 'v2.3.0'}, 65, 'v2.4.0'),
             ({'TEST_PRIORITY': 'none'}, 65, 'Missing kernel feature'),
             ({'TEST_RUNTIME': '7'}, 65, 'All four Runtime-v1 switches')]
    for overrides, code, expected in cases:
        result = subprocess.run(['sh', '-c', functions + fixture], env=env | overrides,
                                capture_output=True, text=True, timeout=5)
        assert result.returncode == code and expected in result.stdout + result.stderr, result
        assert state.read_text() == 'existing profile\n'
    print(f'PASS: {len(cases)} installer cases; existing settings verified unchanged; isolated host fixtures')
