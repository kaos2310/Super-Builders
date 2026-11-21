from pathlib import Path
import hashlib
import json
import sys
import tomllib
import unittest
import tempfile
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci import lock_compat


class LockCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.raw=Path(__file__).with_name('fixtures').joinpath('b2d01-upstream.Cargo.lock').read_bytes()

    def test_exact_upstream_graph_prunes_only_17_unreachable_packages(self):
        effective,removed=lock_compat.reviewed_lock(self.raw,lock_compat.PIN)
        self.assertEqual(hashlib.sha256(effective).hexdigest(),lock_compat.EFFECTIVE_SHA256)
        self.assertEqual(len(removed),17)
        before=tomllib.loads(self.raw.decode())['package'];after=tomllib.loads(effective.decode())['package']
        identity=lambda p:(p['name'],p['version'],p.get('source',''))
        originals={identity(p):p for p in before}
        self.assertEqual(len(after),265)
        for p in after:self.assertEqual(p,originals[identity(p)])
        self.assertTrue({'ksud','ksuinit'}<={p['name'] for p in after})
        self.assertEqual(lock_compat.prune_unreachable(effective),(effective,[]))

    def test_unreviewed_source_or_lock_is_not_silently_changed(self):
        self.assertEqual(lock_compat.reviewed_lock(self.raw,'a'*40),(self.raw,[]))
        with self.assertRaisesRegex(RuntimeError,'upstream Cargo.lock'):
            lock_compat.reviewed_lock(self.raw+b'\n',lock_compat.PIN)

    def test_lock_receipt_remains_equal_after_json_storage(self):
        effective,removed=lock_compat.reviewed_lock(self.raw,lock_compat.PIN)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'Cargo.lock').write_bytes(effective)
            with patch.object(lock_compat,'inputs',return_value=(self.raw,effective,removed)):
                result=lock_compat.verify(root,lock_compat.PIN)
            self.assertEqual(json.loads(json.dumps(result)),result)

    def test_missing_dependency_and_unexpected_roots_are_rejected(self):
        broken=self.raw.replace(b' "anyhow",',b' "missing-dependency",',1)
        with self.assertRaisesRegex(RuntimeError,'dependency'):
            lock_compat.prune_unreachable(broken)
        with self.assertRaisesRegex(RuntimeError,'roots'):
            lock_compat.prune_unreachable(self.raw.replace(b'name = "ksud"',b'name = "other-root"',1))


if __name__=='__main__':unittest.main()
