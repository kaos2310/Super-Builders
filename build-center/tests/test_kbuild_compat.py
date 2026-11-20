from pathlib import Path
import hashlib
import re
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci.kbuild_compat import adapt_compat_patch, SOURCE_PIN, BASE_FRAGMENT_SHA256

FIXTURE = Path(__file__).with_name('fixtures').joinpath('kbuild-41165.patch')


class KbuildCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.fragment = FIXTURE.read_bytes()
        self.plan = {'sukisu_commit':SOURCE_PIN, 'sukisu_code':41176, 'sukisu_count':3991}
        self.before = b'diff --git a/kernel/first.c b/kernel/first.c\nunchanged first section\n'
        self.after = b'diff --git a/kernel/last.c b/kernel/last.c\nunchanged last section\n'
        self.patch = self.before+self.fragment+self.after

    def test_baseline_fixture_is_the_exact_audited_template(self):
        self.assertEqual(hashlib.sha256(self.fragment).hexdigest(), BASE_FRAGMENT_SHA256)

    def test_refresh_changes_only_the_kbuild_section(self):
        fixed = adapt_compat_patch(self.patch,self.plan)
        old_parts = re.split(rb'(?=^diff --git )',self.patch,flags=re.M)
        new_parts = re.split(rb'(?=^diff --git )',fixed,flags=re.M)
        self.assertEqual(len(old_parts),len(new_parts))
        changed = [i for i,(old,new) in enumerate(zip(old_parts,new_parts)) if old != new]
        self.assertEqual(len(changed),1)
        self.assertTrue(new_parts[changed[0]].startswith(b'diff --git a/kernel/Kbuild '))
        self.assertTrue(fixed.startswith(self.before) and fixed.endswith(self.after))
        self.assertIn(b'-KSU_RUNNER_LDFLAGS :=',fixed)

    def test_refresh_is_idempotent(self):
        fixed = adapt_compat_patch(self.patch,self.plan)
        self.assertEqual(adapt_compat_patch(fixed,self.plan),fixed)

    def test_other_official_source_pins_are_not_rewritten(self):
        other = dict(self.plan,sukisu_commit='a'*40)
        self.assertEqual(adapt_compat_patch(self.patch,other),self.patch)

    def test_wrong_version_mapping_is_rejected(self):
        for key in ('sukisu_code','sukisu_count'):
            with self.assertRaisesRegex(RuntimeError,'source/version mapping'):
                adapt_compat_patch(self.patch,dict(self.plan,**{key:self.plan[key]+1}))

    def test_unreviewed_template_changes_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'baseline Kbuild fragment changed'):
            adapt_compat_patch(self.patch.replace(b'KSU_UAPI_INC',b'OTHER_INCLUDE',1),self.plan)

    def test_missing_or_duplicate_kbuild_sections_are_rejected(self):
        for patch in (self.before+self.after,self.patch+self.fragment):
            with self.assertRaisesRegex(RuntimeError,'exactly one'):
                adapt_compat_patch(patch,self.plan)


if __name__ == '__main__':
    unittest.main()
