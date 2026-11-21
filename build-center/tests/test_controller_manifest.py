import hashlib
import json
from pathlib import Path
import unittest
import tempfile
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.update_controller_manifest import canonical_bytes


class ControllerManifestTests(unittest.TestCase):
    def test_windows_crlf_is_normalized_before_binding_the_github_blob(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'resolver.py'
            path.write_bytes(b'# source\r\nprint("checked")\r\n')
            expected=b'# source\nprint("checked")\n'
            self.assertEqual(canonical_bytes(path),expected)
            self.assertEqual(path.read_bytes(),expected)

    def test_manifest_matches_the_actual_workflow_and_resolver(self):
        manifest=json.loads((ROOT/'controller.json').read_text())
        workflow=ROOT.parent/'.github/workflows/build-center.yml'
        self.assertEqual(manifest['schema'],2)
        self.assertEqual(manifest['source_binding'],'source-request-v1')
        self.assertEqual(manifest['profile'],'S928BXXU6EZJB-EUX-android14-6.1.162')
        self.assertEqual(manifest['workflow_sha256'],hashlib.sha256(workflow.read_bytes()).hexdigest())
        self.assertEqual(manifest['resolver_sha256'],hashlib.sha256((ROOT/'ci/check_updates.py').read_bytes()).hexdigest())
        self.assertEqual(workflow.read_bytes(),(ROOT/'integration/.github/workflows/build-center.yml').read_bytes())


if __name__=='__main__': unittest.main()
