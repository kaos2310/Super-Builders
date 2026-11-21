from pathlib import Path
import hashlib,json,sys,tempfile,unittest,zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci.publish import checked_guard6

HOOKS=['bin/zm-susfs-owner','bin/zm-patch-policy','bin/zm-bootguard','bin/zm-droidspaces-vfs','bin/zm-open-redirect','post-fs-data.sh','boot-completed.sh','service.sh']
PAGES=['webroot/index.html','webroot/susfs-rules.html','webroot/brene75.html','webroot/brene69.html','webroot/susfs-brene.html']

class GuardPublicationTests(unittest.TestCase):
    def setUp(self):
        self.plan={'sukisu_code':41179,'sukisu_commit':'a'*40,'susfs_version':'v2.4.0','susfs_commit':'b'*40}

    def package(self,path,**changes):
        elf=bytearray(64);elf[:6]=b'\x7fELF\x02\x01';elf[18:20]=(183).to_bytes(2,'little')
        members={name:b'original control' for name in HOOKS+PAGES}
        members['bin/susfs-runtime']=bytes(elf)
        members['module.prop']=b'id=meta-zeromount\nversion=guard6.13.brene75.sukisu41179\n'
        manifest={'sukisu_version':41179,'sukisu_pin':'a'*40,'susfs_version':'v2.4.0','susfs_source_pin':'b'*40,'original_controls_preserved':True,'runtime_menu_additive':True,'configuration_preserved':True,'runtime_helper_sha256':hashlib.sha256(elf).hexdigest(),'baseline_files_preserved_sha256':{n:hashlib.sha256(members[n]).hexdigest() for n in HOOKS}}
        manifest.update(changes.pop('manifest',{}))
        members['build-manifest.json']=json.dumps(manifest).encode()
        members.update(changes)
        members['SHA256SUMS']=''.join(hashlib.sha256(data).hexdigest()+'  '+name+'\n' for name,data in members.items()).encode()
        with zipfile.ZipFile(path,'w') as z:
            for name,data in members.items():z.writestr(name,data)

    def test_matching_full_guard_package_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'guard.zip';self.package(path)
            self.assertTrue(checked_guard6(path,self.plan)['runtime_menu_additive'])

    def test_wrong_source_or_replacement_menu_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'guard.zip'
            for change in [{'sukisu_version':41176},{'susfs_source_pin':'c'*40},{'runtime_menu_additive':False},{'original_controls_preserved':False}]:
                self.package(path,manifest=change)
                with self.assertRaises(RuntimeError):checked_guard6(path,self.plan)

    def test_existing_hook_replacement_is_rejected_even_with_new_member_checksums(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'guard.zip';self.package(path,**{'bin/zm-susfs-owner':b'replaced'})
            with self.assertRaisesRegex(RuntimeError,'preserv'):checked_guard6(path,self.plan)

    def test_cached_device_state_and_wrong_architecture_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'guard.zip'
            for extra in [{'webroot/cache.json':b'private state'},{'bin/susfs-runtime':b'not ELF'}]:
                self.package(path,**extra)
                with self.assertRaises(RuntimeError):checked_guard6(path,self.plan)

if __name__=='__main__':unittest.main()
