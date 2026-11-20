"""Regression controls for the exact Nova/native-SELinux/SUS_PATH port."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

CI = Path(__file__).resolve().parents[1]/'ci'
sys.path.insert(0, str(CI))
import nova
import runtime


def plan():
    return {'sukisu_family': 'nova', 'sukisu_repository': 'SukiSU-Nova/SukiSU-Nova',
            'sukisu_commit': nova.PIN, 'sukisu_code': 35004, 'sukisu_count': 4008,
            'sukisu_version_base': 30000, 'sukisu_version_offset': 996,
            'sukisu_version_operator': '+', 'sukisu_tag': 'v3.0.0',
            'susfs_commit': nova.SUSFS_PIN, 'susfs_release_base': nova.SUSFS_BASE,
            'susfs_version': 'v2.4.0', 'profile': 'S928BXXS6EZJ1-EUX-android14-6.1.162'}


class NovaPortTests(unittest.TestCase):
    def test_exact_source_profile_required(self):
        nova.validate(plan())
        for field, wrong in [('sukisu_commit', '0'*40), ('sukisu_code', 41179),
                             ('sukisu_count', 4009), ('sukisu_version_offset', -2815),
                             ('susfs_commit', '1'*40), ('sukisu_repository', 'unofficial/fork')]:
            candidate = dict(plan(), **{field: wrong})
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                nova.validate(candidate)

    def test_full_patch_identity_and_native_selinux_retained(self):
        data = (CI/'compat/nova-35004.patch').read_bytes()
        self.assertEqual(nova.sha(data), nova.COMPAT_NOVA)
        text = data.decode()
        self.assertEqual(text.count('+    case CMD_SUSFS_SET_SUS_PATH_UID_FILTER:'), 1)
        self.assertEqual(text.count('+    susfs_parse_sus_path_app_strings();'), 1)
        self.assertNotIn('diff --git a/kernel/feature/selinux_hide.c ', text)
        for old_feature in ('CMD_SUSFS_SET_PRIORITY_UID_FILTER', 'ksu_susfs_dispatch_path_compat',
                            'CONFIG_KSU_SUSFS_SUS_PATH', 'KSU_NO_PREINIT'):
            self.assertIn(old_feature, text)

    def test_deterministic_kbuild_and_manager_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root/'kernel/Kbuild';target.parent.mkdir()
            settings = ['RELEASE_API_BASE', 'KSU_RELEASE_VER', 'RELEASE_COMMITS',
                        'LOCAL_COUNT', 'KSU_VERSION', 'VERSION_TAG', 'KSU_VERSION_FULL']
            original = 'VERSION_BASE := 30000\nVERSION_OFFSET := 996\n'
            original += '\n'.join(name+' := $(shell unsafe-live-fetch)' for name in settings)+'\n'
            original += ('KSU_PACKAGE_NAME ?= com.sukisu.nova\nKSU_EXPECTED_SIZE ?= 0x35c\n'
                         'KSU_EXPECTED_HASH ?= '+nova.CERT+'\n')
            def git(*args):return (nova.PIN if args[-1]=='HEAD' and 'rev-parse' in args else '4008').encode()
            target.write_text(original)
            with patch.object(nova, 'command', side_effect=git):
                result = nova.configure(root)
                self.assertEqual(nova.configure(root, True), result)
                self.assertEqual(result['version'], 35004)
                self.assertNotIn('unsafe-live-fetch', target.read_text())
                configured = target.read_text()
                for old, bad in [('com.sukisu.nova', 'com.sukisu.ultra'),
                                 (nova.CERT, '0'*64), ('KSU_VERSION := 35004', 'KSU_VERSION := 41179')]:
                    target.write_text(configured.replace(old, bad))
                    with self.assertRaises(RuntimeError):nova.configure(root, True)
                target.write_text(configured)
            with patch.object(nova, 'command', return_value=b'3994'):
                with self.assertRaises(RuntimeError):nova.configure(root, True)

    def test_function_parser_ignores_callers_and_prototypes(self):
        text = ('bool lookup(uid_t uid);\nbool caller(void) {\n if (lookup(10)) { return true; }\n}\n'
                '__attribute__((hot)) bool lookup(uid_t uid)\n{\n return uid == 10;\n}\n')
        begin, end = nova.definition(text, 'lookup')
        self.assertEqual(text[begin:end], '__attribute__((hot)) bool lookup(uid_t uid)\n{\n return uid == 10;\n}')

    def test_uid_gate_rebase_is_exact_and_rejects_drift(self):
        old = b'bool susfs_is_inode_sus_path(struct inode *inode)\n{\n\tif (old_predicate()) { return false; }\n\treturn true;\n}\n'
        new = b'bool susfs_is_inode_sus_path(struct inode *inode)\n{\n\tuid_t uid = current_uid().val % 100000;\n\tif (uid < 10000) { return false; }\n\treturn true;\n}\n'
        local = old.decode().replace('\tif (old_predicate())', nova.UID_GUARD+'\tif (old_predicate())').encode()
        known = {'fs/susfs.c': (nova.sha(old), nova.sha(new))}
        with patch.dict(nova.SUSFS_SOURCE_HASHES, known):
            merged = nova.merge_susfs_file('fs/susfs.c', local, old, new, runtime.three_way)
            self.assertEqual(nova.sus_path_guard(merged.decode(), False), new.decode())
            with self.assertRaises(RuntimeError):nova.merge_susfs_file('fs/susfs.c', old, old, new, runtime.three_way)
            with self.assertRaises(RuntimeError):nova.merge_susfs_file('fs/susfs.c', local, old, new+b'\n', runtime.three_way)

    def test_native_patch_review_rejects_unknown_input(self):
        with self.assertRaises(RuntimeError):nova.review_native_gki_delta(b'changed baseline', b'changed target')

    def test_host_c_semantics_and_negative_controls(self):
        compiler = shutil.which('cc') or shutil.which('gcc')
        if not compiler:self.skipTest('Host C compiler unavailable; Actions and WSL run this check')
        fixture = CI/'compat/nova-sus-path.c'
        review = json.loads((CI/'compat/nova-sus-path-review.json').read_text())
        self.assertEqual(nova.sha(fixture.read_bytes()), review['fixture_sha256'])
        with tempfile.TemporaryDirectory() as directory:
            common = Path(directory)/'common';(common/'fs').mkdir(parents=True)
            (common/'fs/susfs.c').write_bytes(fixture.read_bytes())
            result = nova.test_sus_path(common, compiler, Path(directory)/'tests')
        self.assertEqual(result['variant_exit_codes']['production'], 0)
        self.assertTrue(all(value != 0 for name, value in result['variant_exit_codes'].items() if name != 'production'))
        self.assertFalse(result['kernel_compilation_proven'])
        self.assertFalse(result['device_runtime_tested'])


if __name__ == '__main__':unittest.main()
