from pathlib import Path
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci import userspace_compat as compat

PROFILE=b'pub fn set_sepolicy(pkg: &str, policy: String) -> Result<()> {\n}\n\npub fn set_template(id: &str, template: String) -> Result<()> {\n}\n'
CLI=b'// Other code stays byte-identical\n'+b'\n'.join(before.encode() for before,_ in compat.CALLS)+b'\n// End\n'


class UserspaceCompatTests(unittest.TestCase):
    def test_only_two_owned_arguments_change(self):
        repaired=compat.repaired_cli(compat.PIN,CLI,PROFILE)
        for before,after in compat.CALLS:self.assertIn(after.encode(),repaired);self.assertNotIn(before.encode(),repaired)
        self.assertEqual(repaired.replace(b', policy)',b', &policy)').replace(b', template)',b', &template)'),CLI)

    def test_other_upstream_pins_are_unchanged(self):
        self.assertEqual(compat.repaired_cli('a'*40,CLI,PROFILE),CLI)

    def test_unreviewed_call_or_signature_drift_is_rejected(self):
        cases=[(CLI+CLI,PROFILE),(CLI.replace(b'&policy',b'&other'),PROFILE),
               (CLI,PROFILE.replace(b'policy: String',b'policy: &str'))]
        for cli,profile in cases:
            with self.subTest(cli=cli,profile=profile),self.assertRaises(RuntimeError):
                compat.repaired_cli(compat.PIN,cli,profile)

    def test_real_git_source_and_receipt_are_checked_before_and_after_build(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(tmp);(root/compat.CLI).parent.mkdir(parents=True)
            (root/compat.CLI).write_bytes(CLI);(root/compat.PROFILE).write_bytes(PROFILE)
            subprocess.run(['git','init','-q',str(root)],check=True)
            subprocess.run(['git','-C',str(root),'add','.'],check=True)
            subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@example.invalid',
                            'commit','-qm','fixture'],check=True)
            pin=compat.git(root,'rev-parse','HEAD').decode().strip()
            receipt=root/'receipt.json'
            with patch.object(compat,'PIN',pin):
                result=compat.prepare(root,pin,receipt)
                self.assertTrue(result['applied'])
                self.assertEqual(compat.prepare(root,pin,receipt,True),result)
                self.assertEqual(compat.prepare(root,pin,receipt),result)
                (root/compat.CLI).write_bytes((root/compat.CLI).read_bytes()+b'// drift\n')
                with self.assertRaisesRegex(RuntimeError,'source drift'):compat.prepare(root,pin,receipt,True)
                (root/compat.CLI).write_bytes(compat.repaired_cli(pin,CLI,PROFILE))
                data=json.loads(receipt.read_text());data['applied']=False;receipt.write_text(json.dumps(data))
                with self.assertRaisesRegex(RuntimeError,'receipt drift'):compat.prepare(root,pin,receipt,True)


if __name__=='__main__':unittest.main()
