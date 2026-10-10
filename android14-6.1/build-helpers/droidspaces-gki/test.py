#!/usr/bin/env python3
"""Reject dropped feature values, stale fragment overrides and missing kABI patches."""
import importlib.util
from pathlib import Path
import tarfile
import tempfile
import subprocess
import sys
import unittest

spec = importlib.util.spec_from_file_location('droidspaces', Path(__file__).with_name('configure.py'))
droid = importlib.util.module_from_spec(spec)
spec.loader.exec_module(droid)
PATCHED = '''struct task_struct {
#ifdef CONFIG_SYSVIPC
    // struct sysv_sem sysvsem;
    // struct sysv_shm sysvshm;
    ANDROID_KABI_USE(6, struct sysv_sem sysvsem);
    _ANDROID_KABI_REPLACE(ANDROID_KABI_RESERVE(7); ANDROID_KABI_RESERVE(8), struct sysv_shm sysvshm);
#endif
};
'''

class Tests(unittest.TestCase):
    def test_actual_successful_35220_baseline_only_lacks_recent_match(self):
        baseline = Path(__file__).with_name('baseline-35220.config').read_text(encoding='utf-8')
        droid.verify_runtime_prerequisites(baseline)
        with self.assertRaisesRegex(RuntimeError, 'CONFIG_NETFILTER_XT_MATCH_RECENT=y'):
            droid.verify_config(baseline, False)
        updated = droid.update(baseline, {'NETFILTER_XT_MATCH_RECENT': 'y'})
        droid.verify_config(updated, False)
        droid.verify_runtime_prerequisites(updated)
        self.assertEqual(droid.parse(updated)['CFS_BANDWIDTH'], 'n')
        self.assertEqual(droid.parse(updated)['CGROUP_PIDS'], 'n')

    def test_final_config_cli_checks_preserved_runtime_facilities(self):
        values = droid.desired(False)
        values.update(dict.fromkeys((name for names in droid.RUNTIME_PREREQUISITES.values()
                                     for name in names), 'y'))
        good = droid.update('', values)
        with tempfile.TemporaryDirectory() as work:
            config, receipt = Path(work) / 'final.config', Path(work) / 'receipt.json'
            for missing in (None, 'SECCOMP_FILTER', 'VETH'):
                with self.subTest(missing=missing):
                    text = good if missing is None else good.replace(f'CONFIG_{missing}=y', f'# CONFIG_{missing} is not set')
                    config.write_text(text, encoding='utf-8')
                    result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('configure.py')),
                                             'verify', '--config', str(config), '--receipt', str(receipt)],
                                            text=True, capture_output=True)
                    self.assertEqual(result.returncode == 0, missing is None, result.stderr)
                    if missing is None:
                        self.assertIn('verified_runtime_prerequisites', receipt.read_text())
                        receipt.unlink()
                    else:
                        self.assertIn('CONFIG_' + missing, result.stderr)
                        self.assertFalse(receipt.exists())

    def test_each_requested_feature_must_survive_kconfig(self):
        for limits in (False, True):
            good = droid.update('', droid.desired(limits))
            droid.verify_config(good, limits)
            for symbol in droid.FEATURES + (droid.RESOURCE_LIMITS if limits else ()):
                with self.subTest(limits=limits, symbol=symbol):
                    bad = good.replace(f'CONFIG_{symbol}=y', f'# CONFIG_{symbol} is not set')
                    with self.assertRaises(RuntimeError):
                        droid.verify_config(bad, limits)

    def test_standard_build_rejects_resource_limits(self):
        good = droid.update('', droid.desired(False))
        for symbol in ('CFS_BANDWIDTH', 'CGROUP_PIDS'):
            with self.assertRaises(RuntimeError):
                droid.verify_config(good.replace(f'# CONFIG_{symbol} is not set', f'CONFIG_{symbol}=y'), False)

    def test_duplicate_options_rejected(self):
        with self.assertRaises(RuntimeError):
            droid.verify_config(droid.update('', droid.desired(True)) + 'CONFIG_SYSVIPC=n\n', True)

    def test_identical_source_entries_are_normalized_without_changing_values(self):
        source = ('# preserve this comment\nCONFIG_DAMON=y\nCONFIG_DRIVER=m\n'
                  '# CONFIG_DISABLED is not set\nCONFIG_TEXT="with spaces"\n'
                  'CONFIG_DAMON=y\nCONFIG_DRIVER=m\nCONFIG_DISABLED=n\n'
                  'CONFIG_TEXT="with spaces"\n')
        result, removed = droid.deduplicate_identical(source)
        self.assertEqual(result, ''.join(source.splitlines(keepends=True)[:5]))
        self.assertEqual(droid.parse(result), {'DAMON': 'y', 'DRIVER': 'm',
                                             'DISABLED': 'n', 'TEXT': '"with spaces"'})
        self.assertEqual(removed, dict.fromkeys(('DAMON', 'DRIVER', 'DISABLED', 'TEXT'), 1))
        self.assertEqual(droid.deduplicate_identical(result), (result, {}))

    def test_conflicting_unmanaged_source_entries_are_rejected(self):
        for first, second in (('y', 'm'), ('y', 'n'), ('"first"', '"second"')):
            with self.subTest(first=first, second=second):
                with self.assertRaisesRegex(RuntimeError, 'Conflicting configuration for CONFIG_OTHER'):
                    droid.deduplicate_identical(f'CONFIG_OTHER={first}\nCONFIG_OTHER={second}\n')

    def test_final_config_still_rejects_identical_duplicates(self):
        with self.assertRaisesRegex(RuntimeError, 'Duplicate configuration for CONFIG_DAMON'):
            droid.verify_config(droid.update('', droid.desired(True)) + 'CONFIG_DAMON=y\nCONFIG_DAMON=y\n', True)

    def test_real_samsung_defconfig_duplicate_regression(self):
        archive = Path(__file__).resolve().parents[2] / 'samsung-sm-s928b-17-zzhl-common-port.tar.xz'
        with tarfile.open(archive) as source:
            original = source.extractfile('files/arch/arm64/configs/gki_defconfig').read().decode('utf-8')
        self.assertEqual(original.splitlines().count('CONFIG_DAMON=y'), 2)
        for limits in (False, True):
            with self.subTest(resource_limits=limits), tempfile.TemporaryDirectory() as work:
                common = Path(work)
                (common / 'include/linux').mkdir(parents=True)
                (common / 'include/linux/sched.h').write_text(PATCHED, encoding='utf-8')
                (common / 'Kconfig').write_text('\n'.join('config ' + k for k in droid.desired(True)), encoding='utf-8')
                base, fragment = common / 'gki_defconfig', common / 'sukisu.fragment'
                base.write_text(original, encoding='utf-8')
                fragment.write_text('CONFIG_KSU=y\nCONFIG_KSU=y\nCONFIG_SYSVIPC=n\n', encoding='utf-8')
                receipt = droid.configure(common, base, fragment, limits)
                normalized = base.read_text(encoding='utf-8')
                droid.verify_config(normalized, limits)
                self.assertEqual(receipt['removed_identical_defconfig_entries'],
                                 dict.fromkeys(('DAMON', 'EXT4_FS_SECURITY', 'AUDIT', 'SECURITY_SELINUX'), 1))
                self.assertEqual(receipt['removed_identical_fragment_entries'], {'KSU': 1})
                self.assertEqual(fragment.read_text(encoding='utf-8'), 'CONFIG_KSU=y\n')
                before = base.read_bytes()
                droid.configure(common, base, fragment, limits)
                self.assertEqual(before, base.read_bytes())
                base.write_text(original + '\nCONFIG_DAMON=n\n', encoding='utf-8')
                fragment.write_text('CONFIG_KSU=y\nCONFIG_SYSVIPC=n\n', encoding='utf-8')
                before, overlay_before = base.read_bytes(), fragment.read_bytes()
                with self.assertRaisesRegex(RuntimeError, 'Conflicting configuration for CONFIG_DAMON'):
                    droid.configure(common, base, fragment, limits)
                self.assertEqual(before, base.read_bytes())
                self.assertEqual(overlay_before, fragment.read_bytes())

    def test_exact_tree_and_fragment_override_removal(self):
        with tempfile.TemporaryDirectory() as work:
            common = Path(work)
            (common / 'include/linux').mkdir(parents=True)
            header = common / 'include/linux/sched.h'
            header.write_text(PATCHED, encoding='utf-8')
            definitions = common / 'Kconfig'
            definitions.write_text('\n'.join('config ' + k for k in droid.desired(True)), encoding='utf-8')
            base, fragment = common / 'gki_defconfig', common / 'sukisu.fragment'
            base.write_text('CONFIG_SYSVIPC=n\n# CONFIG_SYSVIPC is not set\nCONFIG_KSU=y\n', encoding='utf-8')
            fragment.write_text('# CONFIG_CGROUP_PIDS is not set\nCONFIG_SYSVIPC=n\nCONFIG_KSU=y\n', encoding='utf-8')
            droid.configure(common, base, fragment, True)
            droid.verify_config(base.read_text(encoding='utf-8'), True)
            self.assertEqual(fragment.read_text(encoding='utf-8'), 'CONFIG_KSU=y\n')
            before = base.read_bytes()
            droid.configure(common, base, fragment, True)
            self.assertEqual(before, base.read_bytes())
            for bad in (PATCHED.replace('ANDROID_KABI_USE(6,', '// ANDROID_KABI_USE(6,'),
                        PATCHED.replace('// struct sysv_sem', 'struct sysv_sem')):
                header.write_text(bad, encoding='utf-8')
                with self.assertRaises(RuntimeError):
                    droid.configure(common, base, fragment, True)
                self.assertEqual(before, base.read_bytes())
            header.write_text(PATCHED, encoding='utf-8')
            definitions.write_text('config SYSVIPC\n', encoding='utf-8')
            with self.assertRaises(RuntimeError):
                droid.configure(common, base, fragment, True)

    def test_linux_61_reject_targets(self):
        self.assertNotIn('NETFILTER_XT_TARGET_REJECT', droid.FEATURES)
        self.assertIn('IP_NF_TARGET_REJECT', droid.FEATURES)
        self.assertIn('IP6_NF_TARGET_REJECT', droid.FEATURES)

if __name__ == '__main__':
    unittest.main()
