from pathlib import Path
import hashlib
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci import firmware_profile as profile


class FirmwareProfileTests(unittest.TestCase):
    def test_hashed_inputs_have_identical_bytes_on_git_and_windows(self):
        document, _ = profile.load()
        for name in document['files']:
            with self.subTest(name=name):
                self.assertNotIn(b'\r\n', (profile.DATA / name).read_bytes())

    def test_measured_profile_matches_all_strict_symbols(self):
        document, values = profile.load()
        self.assertEqual(values['SAMSUNG_TARGET_FIRMWARE'], 'S928BXXS6EZJ1')
        self.assertEqual(values['SAMSUNG_TARGET_CSC'], 'EUX')
        self.assertEqual(document['strict_symbols'], 2485)
        self.assertEqual(document['stock_symbols'], 5470)

    def test_unmeasured_target_is_rejected_before_preparation(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'not-created'
            with self.assertRaisesRegex(ValueError, 'independently measured'):
                profile.prepare(target, {'profile': 'S928BXXU6EZIF-EUX-android14-6.1.162'})
            self.assertFalse(target.exists())

    def test_corrupt_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / 'data'
            shutil.copytree(profile.DATA, data)
            (data / 'target.env').write_text('SAMSUNG_TARGET_FIRMWARE=S928BXXU6EZIF\n')
            with patch.object(profile, 'DATA', data):
                with self.assertRaisesRegex(ValueError, 'evidence changed'):
                    profile.load()

    def test_changed_crc_is_rejected_even_with_updated_file_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary) / 'data'
            shutil.copytree(profile.DATA, data)
            strict = profile.crcs((data / 'strict-baseline.tsv').read_text())
            symbol, current = next(iter(strict.items()))
            source = data / 'stock-import-crcs.tsv'
            text = source.read_text()
            original = current + '\t' + symbol + '\n'
            self.assertIn(original, text)
            source.write_text(text.replace(original, '0x00000000\t' + symbol + '\n', 1), encoding='utf-8', newline='\n')
            manifest = json.loads((data / 'profile.json').read_text())
            manifest['files'][source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
            (data / 'profile.json').write_text(json.dumps(manifest))
            with patch.object(profile, 'DATA', data):
                with self.assertRaisesRegex(ValueError, 'strict Samsung baseline'):
                    profile.load()


if __name__ == '__main__':
    unittest.main()
