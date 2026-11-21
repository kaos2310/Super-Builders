from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci.versioning import formula_from_kbuild,version_code,validate_mapping

FIXTURES=Path(__file__).parent/'fixtures'


class VersioningTests(unittest.TestCase):
    def test_both_actual_upstream_schemes(self):
        for name,count,code in [('kbuild-41183-upstream',3998,41183),('kbuild-nova-upstream',4008,35004)]:
            formula=formula_from_kbuild((FIXTURES/name).read_text(encoding='utf-8'))
            self.assertEqual(version_code(count,formula),code)
            validate_mapping({'sukisu_count':count,'sukisu_code':code,'sukisu_version_formula':formula})

    def test_new_versions_and_offsets_do_not_require_a_whitelist(self):
        source=(FIXTURES/'kbuild-nova-upstream').read_text(encoding='utf-8')
        self.assertEqual(version_code(4009,formula_from_kbuild(source)),35005)
        source=source.replace('VERSION_OFFSET  := 996','VERSION_OFFSET  := 1000')
        self.assertEqual(version_code(4009,formula_from_kbuild(source)),35009)

    def test_extra_arithmetic_shell_or_ambiguous_assignments_are_rejected(self):
        source=(FIXTURES/'kbuild-nova-upstream').read_text(encoding='utf-8')
        invalid=[source.replace('$(LOCAL_COUNT) + $(VERSION_OFFSET)','$(LOCAL_COUNT) * $(VERSION_OFFSET)'),
                 source.replace('$(LOCAL_COUNT) + $(VERSION_OFFSET)','$(LOCAL_COUNT) + $(VERSION_OFFSET) + 1'),
                 source.replace('$(LOCAL_COUNT) + $(VERSION_OFFSET)','$(LOCAL_COUNT) + $(VERSION_OFFSET); echo 1'),
                 source+'\nVERSION_BASE := 40000\n',source+'\nKSU_VERSION := 123\n']
        for text in invalid:
            with self.assertRaises(ValueError):formula_from_kbuild(text)

    def test_plan_cannot_change_the_count_or_formula_result(self):
        plan={'sukisu_count':4008,'sukisu_code':35004,'sukisu_version_formula':{'base':30000,'offset':996,'operation':'+'}}
        for change in ({'sukisu_count':4009},{'sukisu_code':41193},{'sukisu_count':True},{'sukisu_code':'35004'}):
            with self.assertRaises(ValueError):validate_mapping(dict(plan,**change))

    def test_invalid_types_ranges_and_operators(self):
        for count in (True,0,-1,2000001,'4008'):
            with self.assertRaises(ValueError):version_code(count)
        for formula in ({'base':30000,'offset':996,'operation':'*'},
                        {'base':True,'offset':996,'operation':'+'},
                        {'base':30000,'offset':1000001,'operation':'+'}):
            with self.assertRaises(ValueError):version_code(4008,formula)


if __name__=='__main__':unittest.main()
