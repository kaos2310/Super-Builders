"""Exercise the final ZIP's public dispatcher with an inert AArch64 fixture."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

NAMES = ('bin/zm', 'bin/zm-brene75', 'bin/zm-brene76', 'bin/arm64-v8a/zeromount')


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o755)


def main(original, fixed, arm64):
    with tempfile.TemporaryDirectory(prefix='ezjb-prop-watch-') as directory:
        root = Path(directory)
        with zipfile.ZipFile(fixed) as archive:
            for name in NAMES:
                data = archive.read(name).replace(b'#!/system/bin/sh\n', b'#!/bin/sh\n', 1)
                write(root / name, data)
        core = root / 'bin/arm64-v8a/zm-native-core'
        alias = root / NAMES[-1]
        write(core, arm64.read_bytes())
        write(root / 'commands/getprop', b'#!/bin/sh\nprintf "%s\\n" "$TEST_BOOT"\n')
        write(root / 'commands/sleep', b'#!/bin/sh\nkill -TERM "$PPID"\n')
        env = {key: value for key, value in os.environ.items() if not key.startswith('ZM')}
        env.update(PATH=f'{root}/commands:/usr/bin:/bin', TEST_BOOT='1',
                   ZM71_EXTERNAL_FLAG=str(root / 'no-external-owner'))

        def run(*args, **overrides):
            return subprocess.run([str(root / 'bin/zm'), 'prop-watch', *args],
                                  env=env | overrides, text=True, capture_output=True, timeout=5)

        normal = run()
        assert (normal.returncode, normal.stdout, normal.stderr) == (0, 'native prop-watch\n', ''), normal
        repeat = run('--repeat')
        assert (repeat.returncode, repeat.stdout, repeat.stderr) == (-15, 'native prop-watch\n', ''), repeat
        before_boot = run(TEST_BOOT='0')
        assert (before_boot.returncode, before_boot.stdout, before_boot.stderr) == (0, '', ''), before_boot

        # Run the old script once against a tripwire at the genuine shell-alias path.
        with zipfile.ZipFile(original) as archive:
            old = archive.read('bin/zm-brene76').replace(b'#!/system/bin/sh\n', b'#!/bin/sh\n', 1)
        fixed_adapter = (root / 'bin/zm-brene76').read_bytes()
        write(root / 'bin/zm-brene76', old)
        alias_data = alias.read_bytes()
        write(alias, b'#!/bin/sh\nif [ "$1" = prop-watch ]; then echo alias-called; exit 91; fi\nexit 0\n')
        old_result = run()
        assert (old_result.returncode, old_result.stdout) == (91, 'alias-called\n'), old_result
        write(alias, alias_data)
        write(root / 'bin/zm-brene76', fixed_adapter)

        for args in [(), ('--repeat',)]:
            rejected = run(*args, ZM71_NATIVE=str(alias))
            assert rejected.returncode == 65 and not rejected.stdout and 'AArch64' in rejected.stderr, rejected
        core.unlink()
        core.symlink_to(alias)
        rejected = run('--repeat')
        assert rejected.returncode == 65 and not rejected.stdout and 'AArch64' in rejected.stderr, rejected
        core.unlink()
        write(core, alias_data)
        rejected = run()
        assert rejected.returncode == 65 and not rejected.stdout and 'AArch64' in rejected.stderr, rejected

    print(json.dumps({'old_dispatch_hit_shell_alias': True, 'new_dispatch_hit_native_once': True,
                     'repeat_first_pass_native_once': True, 'boot_gate': True,
                     'shell_alias_rejected': True, 'symlink_rejected': True,
                     'platform': 'WSL shell and emulated AArch64 fixture', 'device_tested': False}, indent=2))


if __name__ == '__main__':
    main(*map(Path, sys.argv[1:]))
