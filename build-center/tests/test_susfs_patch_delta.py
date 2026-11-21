from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci.runtime import gki_reference_patches


def section(name,old,new):
    return (f'diff --git a/{name} b/{name}\n--- a/{name}\n+++ b/{name}\n@@ -1 +1 @@\n-{old}\n+{new}\n').encode()


class GkiReferenceDeltaTests(unittest.TestCase):
    def test_unchanged_vendor_context_is_not_reapplied(self):
        untouched=section('fs/exec.c','upstream include','susfs include')
        before=section('fs/namei.c','original','old susfs')
        after=section('fs/namei.c','original','updated susfs')
        patches,paths,excluded=gki_reference_patches(untouched+before,untouched+after)
        self.assertEqual(paths,['fs/namei.c']);self.assertEqual(excluded,[])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'fs').mkdir()
            (root/'fs/exec.c').write_bytes(b'Samsung-specific include\n')
            for patch,expected in zip(patches,('old susfs\n','updated susfs\n')):
                (root/'fs/namei.c').write_bytes(b'original\n')
                result=subprocess.run(['git','apply','--no-index','-'],input=patch,cwd=root,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr.decode(errors='replace'))
                self.assertEqual((root/'fs/namei.c').read_text(),expected)
                self.assertEqual((root/'fs/exec.c').read_text(),'Samsung-specific include\n')

    def test_legacy_selinux_hooks_removed_by_the_native_port_are_not_reintroduced(self):
        for name in ('security/selinux/hooks.c','security/selinux/selinuxfs.c'):
            patches,paths,excluded=gki_reference_patches(section(name,'native','legacy old'),section(name,'native','legacy new'))
            self.assertEqual(patches,[b'',b'']);self.assertEqual(paths,[]);self.assertEqual(excluded,[name])

    def test_services_and_other_supported_kernel_changes_remain_in_the_delta(self):
        name='security/selinux/ss/services.c'
        old,new=section(name,'base','old'),section(name,'base','new')
        self.assertEqual(gki_reference_patches(old,new),([old,new],[name],[]))

    def test_path_traversal_renames_duplicates_and_layout_changes_fail_closed(self):
        valid=section('fs/namei.c','a','b')
        invalid=[section('../outside','a','b'),valid+valid,
                 valid.replace(b'b/fs/namei.c',b'b/fs/other.c')]
        for raw in invalid:
            with self.subTest(raw=raw),self.assertRaises(RuntimeError):gki_reference_patches(raw,raw)
        with self.assertRaises(RuntimeError):gki_reference_patches(valid,valid+section('fs/new.c','a','b'))

    def test_metadata_only_changes_still_require_valid_reference_application(self):
        old=section('fs/namei.c','base','value')
        new=old.replace(b'@@ -1 +1 @@',b'@@ -2 +2 @@')
        patches,paths,excluded=gki_reference_patches(old,new)
        self.assertEqual(paths,['fs/namei.c']);self.assertEqual(patches,[old,new])


if __name__=='__main__':unittest.main()
