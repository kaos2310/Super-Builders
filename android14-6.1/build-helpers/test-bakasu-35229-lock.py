#!/usr/bin/env python3
"""Check the bounded repair against the exact pinned upstream lockfiles."""
from pathlib import Path
import sys
import shutil
import tomllib
import unittest
import uuid
from unittest.mock import patch

import bakasu_35229_lock as repair

SOURCE = Path(sys.argv.pop(1)).resolve()
ORIGINAL = repair.upstream(SOURCE, repair.LOCK)
KSUD = repair.upstream(SOURCE, "userspace/ksud/Cargo.lock")
MANIFESTS = [repair.upstream(SOURCE, f"userspace/{crate}/Cargo.toml") for crate in ("ksuinit", "ksud")]


class LockRepairTests(unittest.TestCase):
    def test_ksud_adds_only_existing_prettyplease_dependency(self):
        after_bytes=repair.repair_ksud_bytes(KSUD,MANIFESTS[1])
        before=tomllib.loads(KSUD.decode())
        after=tomllib.loads(after_bytes.decode())
        changed=[(a,b) for a,b in zip(before['package'],after['package']) if a!=b]
        self.assertEqual(len(before['package']),len(after['package']))
        self.assertEqual(len(changed),1)
        a,b=changed[0]
        self.assertEqual(a['name'],'ksud')
        self.assertEqual(b['dependencies'],sorted(a['dependencies']+['prettyplease']))
        b['dependencies']=a['dependencies']
        self.assertEqual(a,b)
        import difflib
        delta=[line for line in difflib.ndiff(KSUD.decode().splitlines(),after_bytes.decode().splitlines()) if line.startswith(('+ ','- '))]
        self.assertEqual(delta,['+  "prettyplease",'])

    def test_ksud_rejects_changed_manifest_pin(self):
        with self.assertRaises(RuntimeError):
            repair.repair_ksud_bytes(KSUD,MANIFESTS[1].replace(b'=0.2.37',b'=0.2.38'))

    def test_ksud_rejects_changed_locked_package(self):
        with self.assertRaises(RuntimeError):
            repair.repair_ksud_bytes(KSUD.replace(b'version = "0.2.37"',b'version = "0.2.38"'),MANIFESTS[1])

    def test_ksud_rejects_duplicate_root(self):
        import re
        root=re.findall(rb'(?m)^\[\[package\]\]\nname = "ksud"\n(?:(?!\[\[).)*',KSUD,re.S)[0]
        with self.assertRaises(RuntimeError):
            repair.repair_ksud_bytes(KSUD+root,MANIFESTS[1])

    def test_ksud_apply_is_idempotent_and_rejects_unrelated_changes(self):
        import tempfile
        fixed=repair.repair_ksud_bytes(KSUD,MANIFESTS[1])
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/repair.KSUD_LOCK;path.parent.mkdir(parents=True);path.write_bytes(KSUD)
            with patch.object(repair,'expected_ksud_lock',return_value=(KSUD,fixed,{})):
                repair.apply_ksud(root);repair.apply_ksud(root);repair.verify_ksud(root)
                path.write_bytes(fixed+b'# unexpected\n')
                with self.assertRaises(RuntimeError):repair.apply_ksud(root)
                with self.assertRaises(RuntimeError):repair.verify_ksud(root)

    def test_rejects_another_source_pin(self):
        with patch.object(repair.subprocess, 'check_output', return_value='0' * 40 + '\n'):
            with self.assertRaises(RuntimeError):
                repair.expected_lock(SOURCE)

    def test_only_libc_source_changes(self):
        before = tomllib.loads(ORIGINAL.decode())
        after = tomllib.loads(repair.repair_bytes(ORIGINAL, KSUD, MANIFESTS).decode())
        self.assertEqual(len(before['package']), len(after['package']))
        changed = [(a, b) for a, b in zip(before['package'], after['package']) if a != b]
        self.assertEqual(len(changed), 1)
        a, b = changed[0]
        self.assertEqual((a['name'], a['version']), ('libc', '0.2.189'))
        self.assertEqual((b['name'], b['version']), ('libc', '0.2.190'))
        self.assertEqual(set(a) - set(b), {'checksum'})
        self.assertIn(repair.LIBC_REV, b['source'])

    def test_rejects_changed_manifest_revision(self):
        manifests = [m.replace(repair.LIBC_REV.encode(), b'0' * 40) for m in MANIFESTS]
        with self.assertRaises(RuntimeError):
            repair.repair_bytes(ORIGINAL, KSUD, manifests)

    def test_rejects_different_libc_version(self):
        with self.assertRaises(RuntimeError):
            repair.repair_bytes(ORIGINAL.replace(b'0.2.189', b'0.2.188'), KSUD, MANIFESTS)

    def test_rejects_wrong_upstream_git_source(self):
        with self.assertRaises(RuntimeError):
            repair.repair_bytes(ORIGINAL, KSUD.replace(repair.LIBC_REV.encode(), b'0' * 40), MANIFESTS)

    def test_rejects_duplicate_libc(self):
        with self.assertRaises(RuntimeError):
            repair.repair_bytes(ORIGINAL + repair.libc_block(ORIGINAL), KSUD, MANIFESTS)

    def test_apply_is_idempotent_and_rejects_unrelated_edits(self):
        fixed = repair.repair_bytes(ORIGINAL, KSUD, MANIFESTS)
        root = SOURCE.parent / ('lock-repair-test-' + uuid.uuid4().hex)
        root.mkdir()
        try:
            path = root / repair.LOCK
            path.parent.mkdir(parents=True)
            path.write_bytes(ORIGINAL)
            with patch.object(repair, 'expected_lock', return_value=(ORIGINAL, fixed, {})):
                repair.apply(root)
                self.assertEqual(path.read_bytes(), fixed)
                repair.apply(root)
                repair.verify(root)
                altered = fixed.replace(b'name = "anyhow"', b'name = "unexpected"')
                path.write_bytes(altered)
                with self.assertRaises(RuntimeError):
                    repair.apply(root)
                with self.assertRaises(RuntimeError):
                    repair.verify(root)
                self.assertEqual(path.read_bytes(), altered)
        finally:
            if root.resolve().parent != SOURCE.parent or not root.name.startswith('lock-repair-test-'):
                raise RuntimeError('Unexpected test cleanup path')
            shutil.rmtree(root)


if __name__ == '__main__':
    unittest.main()
