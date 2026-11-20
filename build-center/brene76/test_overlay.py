"""Test preservation/provenance boundaries with an explicitly synthetic tool fixture.

No release archive is produced here. The genuine freshly compiled matching tool
is mandatory in guard6/package.py and the complete CI module acceptance test.
"""
from pathlib import Path
import argparse,copy,hashlib,json,tempfile,unittest,zipfile
from apply import apply

HELPERS=None
HOOKS=('bin/zm-susfs-owner','bin/zm-patch-policy','bin/zm-bootguard',
 'bin/zm-droidspaces-vfs','bin/zm-open-redirect','post-fs-data.sh','boot-completed.sh','service.sh')

class OverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        baseline=next(HELPERS.glob('zeromount-package-*/module-base.zip'))
        with zipfile.ZipFile(baseline) as archive:
            self.original={n:archive.read(n) for n in archive.namelist()}
        self.original['customize.sh']=(baseline.parent/'customize.sh').read_bytes()
        self.original['webroot/assets/zm-susfs-hub.mjs']=b'preserved-runtime-addon-fixture'
        self.members=dict(self.original)
        # A genuine ARM64 binary, used only as a no-execution transport fixture.
        self.raw=self.original['bin/arm64-v8a/zm-native-core']
        self.tool=self.root/'unit-fixture-not-a-release-cli'
        self.tool.write_bytes(self.raw)
        self.source_dir=next(HELPERS.glob('resusfs-*-240'))
        self.source=json.loads((self.source_dir/'SOURCE.json').read_text())
        self.proof=dict(self.source,repository='https://gitlab.com/simonpunk/susfs4ksu',
            sha256=hashlib.sha256(self.raw).hexdigest(),bytes=len(self.raw),
            target='aarch64-linux-android26',built_from_official_c_sources=True,test_fixture=True)
        self.write_proof()
    def write_proof(self):
        (self.root/'SUSFS-TOOL-BUILD.json').write_text(json.dumps(self.proof),encoding='utf-8')
    def test_full_baseline_hooks_and_classic_pages_retained(self):
        report=apply(self.members,self.tool,self.source,self.source_dir/'upstream')
        for name in HOOKS+('bin/arm64-v8a/zm-native-core','bin/zm-brene71','webroot/assets/zm-susfs-hub.mjs'):
            self.assertEqual(self.members[name],self.original[name],name)
        for name in ('webroot/susfs-rules.html','webroot/brene75.html','webroot/brene69.html','webroot/brene76.html'):
            self.assertIn(name,self.members)
        for raw in (self.members['webroot/brene76.html'],self.members['webroot/assets/brene76.mjs']):
            self.assertNotIn('Ã',raw.decode());self.assertNotIn('Â',raw.decode())
        self.assertEqual(self.members['webroot/assets/zm-susfs-hub.mjs'],self.original['webroot/assets/zm-susfs-hub.mjs'])
        self.assertEqual(report['version'],'0.0.76')
        self.assertIn('SUS_PATH: Apps mit sichtbaren Pfaden',self.members['webroot/brene76.html'].decode())
        self.assertNotIn('data/local/tmp',report['new_features'])
    def test_old_command_aliases_forward_to_preserving_adapter(self):
        apply(self.members,self.tool,self.source,self.source_dir/'upstream')
        self.assertIn(b'brene71|brene75|brene76)',self.members['bin/zm'])
        self.assertIn(b'zm-brene76',self.members['bin/zm-brene75'])
        self.assertEqual(self.members['bin/zm-brene71'],self.original['bin/zm-brene71'])
    def test_no_standalone_archive_hook_is_imported(self):
        report=apply(self.members,self.tool,self.source,self.source_dir/'upstream')
        self.assertFalse(report['standalone_hooks_installed'])
        self.assertFalse(report['standalone_scripts_executed'])
        for name in ('remove_ksu_directory.sh','config.sh','utils.sh','inotify.sh'):
            self.assertNotIn(name,self.members)
        self.assertIn('upstream/BRENE-v0.0.76.zip',self.members)
        self.assertIn('BRENE76-DELTA-75-76.json',self.members)
    def test_missing_stale_tampered_or_other_source_proof_rejected(self):
        original=copy.deepcopy(self.proof)
        for key,value in [('pin','0'*40),('sha256','0'*64),('bytes',0),
          ('target','x86_64-linux-gnu'),('built_from_official_c_sources',False),
          ('source_files_sha256',{'features/sus_path_uid_filter.c':'other'})]:
            self.proof={**original,key:value};self.write_proof()
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                apply(dict(self.original),self.tool,self.source,self.source_dir/'upstream')
        (self.root/'SUSFS-TOOL-BUILD.json').unlink()
        with self.assertRaises(FileNotFoundError):apply(dict(self.original),self.tool,self.source,self.source_dir/'upstream')
    def test_malformed_or_wrong_arch_tool_rejected(self):
        for data in (b'script',b'\x7fELF\x02\x01'+b'\0'*58):
            self.tool.write_bytes(data)
            self.proof.update(sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
            self.write_proof()
            with self.assertRaises(RuntimeError):apply(dict(self.original),self.tool,self.source,self.source_dir/'upstream')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--helpers',type=Path,required=True)
    args,remaining=parser.parse_known_args();HELPERS=args.helpers
    unittest.main(argv=[__file__,*remaining])
