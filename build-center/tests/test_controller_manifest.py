import hashlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ControllerManifestTests(unittest.TestCase):
    def test_manifest_matches_the_actual_workflow_and_resolver(self):
        manifest=json.loads((ROOT/'controller.json').read_text())
        workflow=ROOT.parent/'.github/workflows/build-center.yml'
        self.assertEqual(manifest['schema'],2)
        self.assertEqual(manifest['source_binding'],'source-request-v1')
        self.assertEqual(manifest['profile'],'S928BXXS6EZJ1-EUX-android14-6.1.162')
        self.assertEqual(manifest['workflow_sha256'],hashlib.sha256(workflow.read_bytes()).hexdigest())
        self.assertEqual(manifest['resolver_sha256'],hashlib.sha256((ROOT/'ci/check_updates.py').read_bytes()).hexdigest())
        self.assertEqual(workflow.read_bytes(),(ROOT/'integration/.github/workflows/build-center.yml').read_bytes())


if __name__=='__main__': unittest.main()
