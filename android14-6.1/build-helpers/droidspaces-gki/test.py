#!/usr/bin/env python3
"""Reject dropped feature values, stale fragment overrides and missing kABI patches."""
import importlib.util
from pathlib import Path
import tempfile
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
