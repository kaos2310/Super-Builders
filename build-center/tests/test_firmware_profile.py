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
    def test_device_identity_uses_measured_archives_images_and_timestamp(self):
        _, values = profile.load()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'device-profiles.json'
            other = {'stock_kernel': {'release': 'unrelated'}}
            baseline = {'firmware': 'S928BXXU6EZIF', 'stock_kernel': {},
                        'firmware_archives': {key: {} for key in ('ap', 'bl', 'keep_oem_unlock_bl', 'cp', 'csc', 'home_csc')}}
            path.write_text(json.dumps({'devices': {'e3q': baseline, 'lake': other}}))
            profile.prepare_device_profile(path, values)
            document = json.loads(path.read_text())
            target = document['devices']['e3q']
            self.assertEqual(document['devices']['lake'], other)
            self.assertEqual(target['firmware'], values['SAMSUNG_TARGET_FIRMWARE'])
            self.assertEqual('6.1.162' + target['stock_kernel']['release'], values['SAMSUNG_TARGET_KERNEL_RELEASE'])
            self.assertEqual('#1 SMP PREEMPT ' + target['stock_kernel']['build_timestamp'], values['SAMSUNG_TARGET_KERNEL_VERSION_STRING'])
            evidence = json.loads((profile.DATA / 'evidence.json').read_text())
            self.assertEqual(target['stock_images'], evidence['stock_images'])
            for key, archive in target['firmware_archives'].items():
                self.assertEqual(archive['sha256'], evidence['archives'][key]['sha256'])

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
