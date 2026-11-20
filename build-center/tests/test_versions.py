from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci.versions import identify,validate,REPOSITORY

class VersionTests(unittest.TestCase):
    def text(self,base,offset,operator):
        return f'VERSION_BASE := {base}\nVERSION_OFFSET := {offset}\nKSU_VERSION := $(shell expr $(VERSION_BASE) + $(LOCAL_COUNT) {operator} $(VERSION_OFFSET))\n'
    def test_nova_main_and_release_use_the_official_reset(self):
        for count,code in [(4008,35004),(4004,35000)]:
            result=identify(self.text(30000,996,'+'),count)
            self.assertEqual(result['sukisu_code'],code)
            validate(dict(result,sukisu_count=count,sukisu_repository=REPOSITORY))
    def test_historical_ultra_mapping_remains_available(self):
        self.assertEqual(identify(self.text(40000,2815,'-'),3994)['sukisu_code'],41179)
        validate({'sukisu_code':41179,'sukisu_count':3994})
    def test_unknown_mixed_or_shallow_formulas_are_rejected(self):
        for text,count in [(self.text(30000,996,'-'),4008),(self.text(40000,996,'+'),4008),(self.text(30000,996,'+'),1)]:
            with self.assertRaises(ValueError):identify(text,count)
    def test_wrong_nova_identity_or_metadata_is_rejected(self):
        good=dict(identify(self.text(30000,996,'+'),4008),sukisu_count=4008,sukisu_repository=REPOSITORY)
        for changes in [{'sukisu_code':41179},{'sukisu_version_operator':'-'},{'sukisu_repository':'other/fork'}]:
            with self.assertRaises(ValueError):validate(dict(good,**changes))

if __name__=='__main__':unittest.main()
