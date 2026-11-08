import importlib.util, tempfile, unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('release240',Path(__file__).with_name('release240.py'))
release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)

class ReleaseTests(unittest.TestCase):
    def test_unknown_header_is_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            common=Path(directory);header=common/'include/linux/susfs.h';header.parent.mkdir(parents=True)
            original=release.OLD+b'\nunknown ABI contents\n';header.write_bytes(original)
            with self.assertRaises(RuntimeError):release.apply(common)
            self.assertEqual(header.read_bytes(),original)
            self.assertFalse((common/'.susfs-release240.json').exists())

    def test_unknown_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            common=Path(directory);header=common/'include/linux/susfs.h';header.parent.mkdir(parents=True)
            original=b'#define SUSFS_VERSION "v2.5.0"\n';header.write_bytes(original)
            with self.assertRaises(RuntimeError):release.apply(common)
            self.assertEqual(header.read_bytes(),original)

if __name__=='__main__':unittest.main()
