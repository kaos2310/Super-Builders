#!/usr/bin/env python3
"""Replay the overlay against a module snapshot and prove unrelated files survive."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import shutil
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('zm_ui_apply', HERE/'apply.py')
overlay = importlib.util.module_from_spec(spec); spec.loader.exec_module(overlay)
SOURCE = None


def hashes(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file()}


class OverlayTests(unittest.TestCase):
    def test_replay_and_idempotence(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            root = Path(temporary)/'module'
            shutil.copytree(SOURCE/'webroot', root/'webroot')
            (root/'bin').mkdir();(root/'bin'/'unchanged').write_bytes(b'backend\x00unchanged')
            (root/'saved-config').write_text('enabled=false\n',encoding='utf-8')
            before = hashes(root)
            receipt = overlay.apply(root)
            after = hashes(root)
            for name, digest in before.items():
                if name not in receipt['changed_files_sha256']:
                    self.assertEqual(after[name], digest, name)
            self.assertEqual(after['bin/unchanged'], before['bin/unchanged'])
            self.assertEqual(after['saved-config'], before['saved-config'])
            brene = (root/'webroot/assets/brene75.mjs').read_text(encoding='utf-8')
            self.assertIn('prüfen SUSFS v2.4.0 sowie OPEN_REDIRECT',brene)
            self.assertNotIn('prüfen SUSFS v2.3.0 sowie OPEN_REDIRECT',brene)
            text = (root/'webroot/index.html').read_text(encoding='utf-8')
            self.assertNotIn('position:fixed;right:12px',text)
            settings = next((root/'webroot/assets').glob('SettingsTab-*.js')).read_text(encoding='utf-8')
            self.assertIn('createSusfsEntry(document)',settings)
            for key in ('kernel_umount','sync_su_compat','try_umount','hide_nonstandard_sdcard'):
                self.assertIn(f'store.settings.brene.{key}',settings)
            for name in ('susfs-rules.html','brene75.html','brene69.html'):
                page=(root/'webroot'/name).read_text(encoding='utf-8')
                self.assertIn('class="zm-integrated"',page)
                self.assertIn('assets/zm-susfs.css',page)
                self.assertIn('aria-label="SUSFS und BRENE"',page)
                self.assertNotIn('ReSukiSU 35187',page)
                self.assertNotIn('<style>',page)
            self.assertEqual(overlay.apply(root)['changed_files_sha256'],{})
            self.assertEqual(hashes(root),after)

    def test_refuses_unknown_native_assets(self):
        with tempfile.TemporaryDirectory(dir=HERE) as temporary:
            root=Path(temporary);(root/'webroot/assets').mkdir(parents=True)
            (root/'webroot/index.html').write_text('<html></html>',encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError,'native Settings'):
                overlay.apply(root)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('module',type=Path)
    args=parser.parse_args();SOURCE=args.module.resolve()
    unittest.main(argv=['test.py'])
