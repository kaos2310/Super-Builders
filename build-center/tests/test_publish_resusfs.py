"""Independent publication gates; synthetic transport fixtures are never releases."""
from pathlib import Path
import copy,hashlib,json,sys,tempfile,unittest,warnings,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci import publish


class NovaFixtures(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.plan={'sukisu_family':'nova','sukisu_repository':'SukiSU-Nova/SukiSU-Nova',
            'sukisu_code':35004,'sukisu_count':4008,'sukisu_commit':'1439545f12bffe0263690ba862139b70ee5f20cf',
            'susfs_version':'v2.4.0','susfs_commit':publish.REVIEWED_SUSFS_PIN,
            'profile':'S928BXXS6EZJ1-EUX-android14-6.1.162'}
        elf=bytearray(64);elf[:6]=b'\x7fELF\x02\x01';elf[18:20]=(183).to_bytes(2,'little')
        self.runtime=bytes(elf)+b'runtime fixture'
        self.core=bytes(elf)+b'Guard6 core fixture'
        self.tool=bytes(elf)+b'set_sus_path_uid_filter\0fixture'
        self.sources={'main.c':b'command parser fixture', 'features/sus_path_uid_filter.c':b'native command fixture'}
        self.hooks={name:('reviewed:'+name).encode() for name in publish.REVIEWED_GUARD_HOOKS}
        self.ui={name:('reviewed:'+name).encode() for name in publish.REVIEWED_RESUSFS_UI}
        self.controls={name:('reviewed:'+name).encode() for name in publish.REVIEWED_RESUSFS_CONTROLS}
        for name,values in [('REVIEWED_SUSFS_SOURCES',self.sources),('REVIEWED_GUARD_HOOKS',self.hooks),
                            ('REVIEWED_RESUSFS_UI',self.ui),('REVIEWED_RESUSFS_CONTROLS',self.controls)]:
            context=patch.dict(getattr(publish,name),{key:self.sha(raw) for key,raw in values.items()},clear=True)
            context.start();self.addCleanup(context.stop)
    def sha(self,data):return hashlib.sha256(data).hexdigest()
    def common(self):
        proof={'pin':self.plan['susfs_commit'],'repository':'https://gitlab.com/simonpunk/susfs4ksu',
            'sha256':self.sha(self.tool),'bytes':len(self.tool),'target':'aarch64-linux-android26',
            'built_from_official_c_sources':True,'source_files_sha256':{name:self.sha(raw) for name,raw in self.sources.items()}}
        return {'bin/ksu_susfs':self.tool,'bin/susfs-runtime':self.runtime,
            'SUSFS-TOOL-BUILD.json':json.dumps(proof).encode(),
            **{'source/ksu_susfs/'+name:raw for name,raw in self.sources.items()}}
    def write(self,members,manifest,name='module.zip',checksum_omit=None,duplicate=False):
        members=dict(members);members['build-manifest.json']=json.dumps(manifest).encode()
        members['SHA256SUMS']=''.join(self.sha(data)+'  '+member+'\n' for member,data in sorted(members.items()) if member!=checksum_omit).encode()
        path=self.root/name
        with warnings.catch_warnings():
            warnings.simplefilter('ignore',UserWarning)
            with zipfile.ZipFile(path,'w') as archive:
                for member,raw in members.items():archive.writestr(member,raw)
                if duplicate:archive.writestr('build-manifest.json',members['build-manifest.json'])
        return path
    def guard(self):
        members={**self.common(),**self.hooks,'bin/arm64-v8a/zm-native-core':self.core,'bin/zm-brene76':b'adapter'}
        for name in ('index.html','susfs-rules.html','brene75.html','brene76.html','brene69.html','susfs-brene.html'):
            members['webroot/'+name]=b'original/additive page'
        manifest={'sukisu_family':'nova','sukisu_repository':self.plan['sukisu_repository'],
            'sukisu_count':4008,'sukisu_version':35004,'sukisu_pin':self.plan['sukisu_commit'],
            'susfs_source_pin':self.plan['susfs_commit'],'susfs_version':'v2.4.0','brene_version':'0.0.76',
            'original_controls_preserved':True,'runtime_menu_additive':True,'configuration_preserved':True,
            'runtime_helper_sha256':self.sha(self.runtime),'native_core_sha256':self.sha(self.core),
            'private_susfs_tool_sha256':self.sha(self.tool),'private_susfs_tool_source_pin':self.plan['susfs_commit'],
            'baseline_files_preserved_sha256':{name:self.sha(raw) for name,raw in self.hooks.items()}}
        return members,manifest
    def resusfs(self):
        members={**self.common(),**self.ui,**self.controls,'ReSuSFS.sh':b'original dispatcher',
            'bin/resusfs-path-filter':b'additive adapter','webroot/index.html':b'original UI + addons',
            'webroot/assets/resusfs-path-filter.mjs':b'additive UI'}
        manifest={'module_id':'ReSuSFS','revision':'r3','sukisu_family':'nova',
            'sukisu_repository':self.plan['sukisu_repository'],'sukisu_count':4008,'sukisu_code':35004,
            'sukisu_source_pin':self.plan['sukisu_commit'],'susfs_source_pin':self.plan['susfs_commit'],
            'susfs_version':'v2.4.0','target_profile':self.plan['profile'],
            'original_ui_preserved':True,'runtime_ui_is_separate_addition':True,
            'existing_config_overwritten':False,'owner_transferred':False,'global_cli_replaced':False,
            'susfs_tool_sha256':self.sha(self.tool),'runtime_helper_sha256':self.sha(self.runtime),
            'unchanged_files_sha256':{name:self.sha(raw) for name,raw in self.ui.items()},
            'preserved_r2_files_sha256':{name:self.sha(raw) for name,raw in self.controls.items()},
            'sus_path_uid_filter':{'source_pin':self.plan['susfs_commit'],'command':'set_sus_path_uid_filter',
                'kernel_command_hex':'0x55554','semantics':'selected_app_uids_can_see_sus_path_paths',
                'kernel_readback_available':False,'status_issues_mutation':False,'native_support_probed_on_read':False}}
        return members,manifest


class ReSuSFSPublicationTests(NovaFixtures):
    def test_matching_complete_nova_package_accepted(self):
        members,manifest=self.resusfs();path=self.write(members,manifest)
        self.assertEqual(publish.checked_resusfs(path,self.plan)['revision'],'r3')
    def test_wrong_kernel_source_family_profile_or_preservation_rejected(self):
        members,original=self.resusfs()
        changes={'sukisu_code':41179,'sukisu_count':4009,'sukisu_source_pin':'0'*40,
            'sukisu_family':'ultra','sukisu_repository':'SukiSU-Ultra/SukiSU-Ultra','susfs_source_pin':'0'*40,
            'susfs_version':'v2.3.0','target_profile':'old','revision':'r2','original_ui_preserved':False,
            'runtime_ui_is_separate_addition':False,'existing_config_overwritten':True,
            'owner_transferred':True,'global_cli_replaced':True}
        for key,value in changes.items():
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                publish.checked_resusfs(self.write(members,{**original,key:value}),self.plan)
    def test_missing_addon_or_original_ui_rejected_even_with_new_checksums(self):
        original,manifest=self.resusfs()
        for name in ('bin/resusfs-path-filter','webroot/assets/resusfs-path-filter.mjs',*self.ui.keys()):
            members=dict(original);members.pop(name)
            with self.subTest(name=name),self.assertRaises(RuntimeError):
                publish.checked_resusfs(self.write(members,manifest),self.plan)
    def test_rehashed_replacement_of_classic_controls_rejected(self):
        members,manifest=self.resusfs();name=next(iter(self.controls));members[name]=b'replaced'
        manifest['preserved_r2_files_sha256'][name]=self.sha(members[name])
        with self.assertRaises(RuntimeError):publish.checked_resusfs(self.write(members,manifest),self.plan)
    def test_unsafe_duplicate_incomplete_or_corrupt_archive_rejected(self):
        members,manifest=self.resusfs()
        for extra in ('../outside','/absolute','bad\\path'):
            with self.subTest(extra=extra),self.assertRaises(RuntimeError):
                publish.checked_resusfs(self.write({**members,extra:b'x'},manifest),self.plan)
        for kwargs in ({'duplicate':True},{'checksum_omit':'ReSuSFS.sh'}):
            with self.subTest(kwargs=kwargs),self.assertRaises(RuntimeError):
                publish.checked_resusfs(self.write(members,manifest,**kwargs),self.plan)
        path=self.write(members,manifest);data=bytearray(path.read_bytes())
        pos=data.index(self.runtime);data[pos+10]^=1;path.write_bytes(data)
        with self.assertRaises((RuntimeError,zipfile.BadZipFile)):publish.checked_resusfs(path,self.plan)
    def test_native_proof_and_source_bytes_fail_closed(self):
        original,manifest=self.resusfs();proof=json.loads(original['SUSFS-TOOL-BUILD.json'])
        for key,value in [('pin','0'*40),('sha256','0'*64),('bytes',0),('target','x86_64'),
             ('built_from_official_c_sources',False),('source_files_sha256',{}),('test_fixture',True)]:
            members={**original,'SUSFS-TOOL-BUILD.json':json.dumps({**proof,key:value}).encode()}
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                publish.checked_resusfs(self.write(members,manifest),self.plan)
        members={**original,'source/ksu_susfs/main.c':b'tampered'}
        with self.assertRaises(RuntimeError):publish.checked_resusfs(self.write(members,manifest),self.plan)
    def test_wrong_architecture_or_manifest_digest_rejected(self):
        original,manifest=self.resusfs()
        for name in ('bin/ksu_susfs','bin/susfs-runtime'):
            with self.subTest(name=name),self.assertRaises(RuntimeError):
                publish.checked_resusfs(self.write({**original,name:b'not ELF'},manifest),self.plan)
        with self.assertRaises(RuntimeError):
            publish.checked_resusfs(self.write(original,{**manifest,'susfs_tool_sha256':'0'*64}),self.plan)
    def test_uid_filter_mutation_on_read_or_wrong_allowlist_semantics_rejected(self):
        members,manifest=self.resusfs()
        for key,value in [('command','set_priority_uid_filter'),('kernel_command_hex','0x55553'),
             ('semantics','hide_these_uids'),('kernel_readback_available',True),
             ('status_issues_mutation',True),('native_support_probed_on_read',True)]:
            changed=copy.deepcopy(manifest);changed['sus_path_uid_filter'][key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                publish.checked_resusfs(self.write(members,changed),self.plan)

if __name__=='__main__':unittest.main()
