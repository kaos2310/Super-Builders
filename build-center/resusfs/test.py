#!/usr/bin/env python3
"""Run real ReSuSFS shell/installer boundaries in isolated fake Android trees."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile

HERE = Path(__file__).resolve().parent
PARSER = argparse.ArgumentParser()
PARSER.add_argument('--legacy-dir', type=Path, required=True)
PARSER.add_argument('--zip', type=Path)
ARGS, REST = PARSER.parse_known_args()
LEGACY = ARGS.legacy_dir.resolve()
MOCK_TOOL = '''#!/usr/bin/env python3
import json,os,sys
with open(os.environ['MOCK_CALLS'],'a') as f:f.write(json.dumps(sys.argv[1:])+'\\n')
a=sys.argv[1:]
if a==['show','version']:print(os.environ.get('MOCK_VERSION','v2.4.0'))
elif a==['show','enabled_features']:
 if os.environ.get('MOCK_FEATURE','yes')=='yes':print('CONFIG_KSU_SUSFS_SUS_PATH')
elif a and a[0]=='set_sus_path_uid_filter':
 if os.environ.get('MOCK_FAIL'):print('Kernel command unsupported',file=sys.stderr);sys.exit(95)
else:sys.exit(64)
'''


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.phone = self.root / 'phone'
        self.mod = self.phone / 'data/adb/modules/ReSuSFS'
        (self.mod / 'bin').mkdir(parents=True)
        self.tool = self.mod / 'bin/ksu_susfs'
        self.tool.write_text(MOCK_TOOL)
        self.tool.chmod(0o755)
        self.control = self.mod / 'bin/resusfs-control'
        self.control.write_bytes((LEGACY / 'resusfs-control').read_bytes())
        # Only the fixture interpreter path changes; production controller is retained.
        self.control.write_bytes(self.control.read_bytes().replace(b'#!/system/bin/sh', b'#!/bin/sh', 1))
        self.control.chmod(0o755)
        self.calls = self.root / 'calls'
        self.calls.write_text('')
        self.persistent = self.phone / 'data/adb/ReSuSFS'
        self.packages = self.persistent / 'sus-path-visible-packages'
        self.env = dict(os.environ, RESUSFS_ROOT=str(self.phone), RESUSFS_MODDIR=str(self.mod), MOCK_CALLS=str(self.calls))

    def call(self, *args, **env):
        return subprocess.run(['sh', str(HERE / 'resusfs-path-filter'), *args], env=dict(self.env, **env), text=True, capture_output=True)

    def status(self, **env):
        result = self.call('status', **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def setters(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines() if json.loads(line)[0].startswith('set_')]

    def test_open_and_default_restore_do_not_write_any_selection(self):
        state = self.status()
        self.assertTrue(state['write_allowed'])
        self.assertEqual(state['revision'], 'none')
        self.assertFalse(state['selection_saved'])
        self.assertFalse(state['command_support_probed'])
        self.assertFalse(state['kernel_readback_available'])
        self.assertFalse(self.persistent.exists())
        self.assertEqual(self.call('restore').returncode, 0)
        self.assertFalse(self.persistent.exists())
        self.assertEqual(self.setters(), [])

    def test_save_clear_and_restore_use_real_native_cli_argument(self):
        result = self.call('set', 'com.example.one,com.example.two', 'none')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['saved'])
        self.assertEqual(self.packages.read_text(), 'com.example.one,com.example.two\n')
        self.assertEqual(self.call('restore').returncode, 0)
        state = self.status()
        self.assertEqual(self.call('set', '', state['revision']).returncode, 0)
        self.assertEqual(self.packages.read_text(), '\n')
        self.assertEqual(self.setters()[-1], ['set_sus_path_uid_filter', ','])
        self.assertEqual(self.call('restore').returncode, 0)
        self.assertEqual(self.setters()[-1], ['set_sus_path_uid_filter', ','])
        self.assertFalse((self.persistent / 'sus-path-uid.lock').exists())

    def test_stale_ui_cannot_overwrite_new_selection(self):
        self.assertEqual(self.call('set', 'com.example.one', 'none').returncode, 0)
        count = len(self.setters())
        self.assertEqual(self.call('set', 'com.example.two', 'none').returncode, 75)
        self.assertEqual(self.packages.read_text(), 'com.example.one\n')
        self.assertEqual(len(self.setters()), count)

    def test_kernel_error_keeps_existing_selection_and_cleans_temp(self):
        self.assertEqual(self.call('set', 'com.example.one', 'none').returncode, 0)
        rev = self.status()['revision']
        result = self.call('set', 'com.example.two', rev, MOCK_FAIL='yes')
        self.assertEqual(result.returncode, 95)
        self.assertIn('unsupported', result.stderr)
        self.assertEqual(self.packages.read_text(), 'com.example.one\n')
        self.assertEqual(sorted(p.name for p in self.persistent.iterdir()), ['sus-path-visible-packages'])

    def test_old_kernel_and_bad_inputs_cannot_mutate(self):
        for env in ({'MOCK_VERSION': 'v2.3.0'}, {'MOCK_VERSION': 'v2.5.0'}, {'MOCK_FEATURE': 'no'}):
            self.assertFalse(self.status(**env)['write_allowed'])
            self.assertNotEqual(self.call('set', 'com.example.one', 'none', **env).returncode, 0)
        for value in ('com.example.one;id', 'com.example.one\ncom.other.app', ',com.example.one', 'x' * 4097):
            self.assertEqual(self.call('set', value, 'none').returncode, 64)
        self.assertEqual(self.call('set', 'com.example.one', '1--2').returncode, 64)
        self.assertEqual(self.setters(), [])

    def test_other_active_manager_blocks_set_and_restore(self):
        self.assertEqual(self.call('set', 'com.example.one', 'none').returncode, 0)
        rev = self.status()['revision']
        (self.phone / 'data/adb/modules/susfs4ksu').mkdir()
        self.assertFalse(self.status()['write_allowed'])
        count = len(self.setters())
        self.assertEqual(self.call('set', 'com.example.two', rev).returncode, 65)
        self.assertEqual(self.call('restore').returncode, 65)
        self.assertEqual(len(self.setters()), count)
        self.assertEqual(self.packages.read_text(), 'com.example.one\n')

    def test_foreign_zeromount_owner_blocks_without_transfer(self):
        owner = self.phone / 'data/adb/zeromount/susfs-owner'
        owner.parent.mkdir(parents=True)
        owner.write_text('ZeroMount\n')
        self.assertFalse(self.status()['write_allowed'])
        self.assertEqual(self.call('set', 'com.example.one', 'none').returncode, 65)
        self.assertEqual(owner.read_text(), 'ZeroMount\n')
        self.assertFalse(self.persistent.exists())


@unittest.skipUnless(ARGS.zip, 'Pass --zip for final artifact/installer tests')
class ArchiveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(ARGS.zip) as archive:
            assert archive.testzip() is None
            cls.files = {name: archive.read(name) for name in archive.namelist()}

    def test_complete_file_checksums_and_preserved_r2_contract(self):
        for line in self.files['SHA256SUMS'].decode().splitlines():
            digest, name = line.split('  ', 1)
            self.assertEqual(hashlib.sha256(self.files[name]).hexdigest(), digest, name)
        manifest = json.loads(self.files['build-manifest.json'])
        self.assertEqual(manifest['revision'], 'r3')
        self.assertTrue(manifest['original_ui_preserved'])
        self.assertTrue(manifest['runtime_ui_is_separate_addition'])
        self.assertFalse(manifest['existing_config_overwritten'])
        self.assertFalse(manifest['owner_transferred'])
        for name, digest in manifest['preserved_r2_files_sha256'].items():
            self.assertEqual(hashlib.sha256(self.files[name]).hexdigest(), digest, name)
        self.assertEqual(self.files['bin/resusfs-control'], (LEGACY / 'resusfs-control').read_bytes())
        self.assertEqual(self.files['webroot/assets/resusfs-runtime.mjs'], (LEGACY / 'resusfs-runtime.mjs').read_bytes())
        proof = json.loads(self.files['verification/ANDROID-SETTER-PROOF.json'])
        self.assertEqual(proof['controller_sha256'], hashlib.sha256(self.files['bin/resusfs-control']).hexdigest())

    def test_original_assets_defaults_and_runtime_navigation_preserved(self):
        with zipfile.ZipFile(LEGACY / 'module-base.zip') as archive:
            original = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
        for name, data in original.items():
            if name.startswith(('webroot/', 'default/')) and name != 'webroot/index.html':
                self.assertEqual(self.files[name], data, name)
        self.assertIn(b'resusfs-runtime.mjs?r=2', self.files['webroot/index.html'])
        self.assertIn(b'resusfs-path-filter.mjs?r=3', self.files['webroot/index.html'])
        self.assertIn(b'resusfs-control" restore priority', self.files['boot-completed.sh'])
        self.assertIn(b'resusfs-path-filter" restore', self.files['boot-completed.sh'])

    def test_actual_installer_preserves_all_existing_user_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mod = root / 'module'
            for name, data in self.files.items():
                path = mod / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            persistent = root / 'persistent'
            custom = {'config.txt': b'USER=keep\n', 'sus_paths.txt': b'/my/path\n', 'runtime-options': b'uid-gating=0\n',
                      'priority-packages': b'com.user.original\n', 'sus-path-visible-packages': b'com.user.visible\n',
                      'scripts/a.sh': b'echo keep\n', 'scripts_cron.txt': b'1 * * * * mine\n',
                      '.webui_config/custom.css': b':root{--user:keep}\n'}
            for name, data in custom.items():
                path = persistent / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
            tool = mod / 'bin/ksu_susfs'
            tool.write_text(MOCK_TOOL)
            tool.chmod(0o755)
            calls = root / 'calls'
            calls.write_text('')
            script = self.files['customize.sh'].decode().replace('PERSISTENT_DIR=/data/adb/ReSuSFS', 'PERSISTENT_DIR=' + str(persistent))
            harness = root / 'install.sh'
            harness.write_text('ui_print(){ :; };abort(){ echo "$*" >&2;exit 1; };set_perm_recursive(){ :; };set_perm(){ :; };getprop(){ echo arm64-v8a; };\n' + script)
            result = subprocess.run(['sh', str(harness)], env=dict(os.environ, KSU='true', MODPATH=str(mod), MOCK_CALLS=str(calls)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            after = {p.relative_to(persistent).as_posix(): p.read_bytes() for p in persistent.rglob('*') if p.is_file()}
            self.assertEqual(after, custom)
            self.assertEqual([json.loads(line) for line in calls.read_text().splitlines()], [['show', 'version']])


if __name__ == '__main__':
    unittest.main(argv=['test.py', *REST])
