#!/usr/bin/env python3
"""Host integration tests of real shell boundaries using explicit kernel-tool doubles."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,tempfile,unittest,zipfile
HERE=Path(__file__).resolve().parent

MOCK_TOOL=r'''#!/usr/bin/env python3
import os,sys,json
from pathlib import Path
with open(os.environ['MOCK_CALLS'],'a') as f:f.write(json.dumps(['susfs']+sys.argv[1:])+'\n')
a=sys.argv[1:]
if a==['show','version']:print(os.environ.get('MOCK_VERSION','v2.4.0'))
elif a==['show','enabled_features']:
 print('CONFIG_KSU_SUSFS_UID_GATED_HIDING')
 if os.environ.get('MOCK_PRIORITY','yes')=='yes':print('CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER')
elif a==['show','variant']:print('GKI')
elif os.environ.get('MOCK_TOOL_FAIL'):sys.exit(1)
'''
MOCK_RUNTIME=r'''#!/usr/bin/env python3
import os,sys,json
from pathlib import Path
with open(os.environ['MOCK_CALLS'],'a') as f:f.write(json.dumps(['runtime']+sys.argv[1:])+'\n')
p=Path(os.environ['MOCK_STATE']);s=json.loads(p.read_text());a=sys.argv[1:]
if a[0]=='set':
 bits={'uid-gating':1,'hidden-name':2,'unicode-filter':4,'symbol-hiding':8};bit=bits[a[1]]
 if s['generation']!=int(a[3]) or not(s['supported']&bit):sys.exit(75)
 if os.environ.get('MOCK_RUNTIME_FAIL'):sys.exit(75)
 s['enabled']=(s['enabled']|bit) if a[2]=='1' else (s['enabled']&~bit);s['generation']+=1;p.write_text(json.dumps(s))
if os.environ.get('MOCK_BAD_ABI'):s['version']=2
if os.environ.get('MOCK_BAD_READBACK') and a[0]=='status' and s['generation']>12:s['generation']+=1
print(json.dumps(s,separators=(',',':')))
'''

class BoundaryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.phone=self.root/'phone';self.mod=self.phone/'data/adb/modules/ReSuSFS';self.mod.mkdir(parents=True)
  self.zm=self.phone/'data/adb/zeromount';(self.zm/'switches').mkdir(parents=True)
  (self.phone/'data/adb/modules/meta-zeromount').mkdir()
  (self.zm/'susfs-owner').write_text('ReSuSFS\n');(self.zm/'switches/susfs.enabled').write_text('false\n')
  (self.zm/'config.toml').write_text('[susfs]\nenabled = false\n[brene]\nenabled = true\n')
  self.persistent=self.phone/'data/adb/ReSuSFS';self.persistent.mkdir()
  (self.persistent/'config.txt').write_text('CUSTOM_KEY=keep\nENABLE_LOG=0\n')
  (self.persistent/'scripts').mkdir();(self.persistent/'scripts/my.sh').write_text('echo keep\n')
  self.tool=self.root/'tool';self.tool.write_text(MOCK_TOOL);self.tool.chmod(0o755)
  self.runtime=self.root/'runtime';self.runtime.write_text(MOCK_RUNTIME);self.runtime.chmod(0o755)
  self.state=self.root/'kernel.json';self.state.write_text(json.dumps(dict(protocol='kaoslab-susfs-runtime',version=1,size=48,supported=15,enabled=15,generation=12)))
  self.calls=self.root/'calls';self.calls.write_text('')
  self.env=dict(os.environ,RESUSFS_ROOT=str(self.phone),RESUSFS_MODDIR=str(self.mod),RESUSFS_SUSFS_TOOL=str(self.tool),RESUSFS_RUNTIME_TOOL=str(self.runtime),MOCK_STATE=str(self.state),MOCK_CALLS=str(self.calls))
 def run_control(self,*args,ok=None):
  p=subprocess.run(['sh',str(HERE/'resusfs-control'),*args],capture_output=True,text=True,env=self.env)
  if ok is True:self.assertEqual(p.returncode,0,p.stdout+p.stderr)
  if ok is False:self.assertNotEqual(p.returncode,0,p.stdout+p.stderr)
  return p
 def logged(self):return [json.loads(x) for x in self.calls.read_text().splitlines()]
 def writes(self):return [a for a in self.logged() if (a[0]=='runtime' and a[1]=='set') or(a[0]=='susfs' and a[1]!='show')]
 def test_status_is_read_only_and_preserves_profiles(self):
  before={str(p.relative_to(self.phone)):p.read_bytes() for p in self.phone.rglob('*') if p.is_file()}
  state_before=self.state.read_bytes();status=json.loads(self.run_control('status',ok=True).stdout)
  self.assertTrue(status['write_allowed']);self.assertEqual(status['runtime']['generation'],12)
  self.assertEqual(before,{str(p.relative_to(self.phone)):p.read_bytes() for p in self.phone.rglob('*') if p.is_file()})
  self.assertEqual(self.state.read_bytes(),state_before);self.assertEqual(self.writes(),[])
 def test_runtime_updates_exact_bit_and_persists_only_confirmed_choice(self):
  out=json.loads(self.run_control('runtime-set','hidden-name','0','12',ok=True).stdout)
  self.assertEqual((out['enabled'],out['generation']),(13,13))
  self.assertEqual((self.persistent/'runtime-options').read_text(),'hidden-name=0\n')
  self.assertEqual((self.persistent/'config.txt').read_text(),'CUSTOM_KEY=keep\nENABLE_LOG=0\n')
 def test_zero_enabled_mask_is_available_and_can_be_enabled(self):
  state=json.loads(self.state.read_text());state.update(enabled=0,generation=5);self.state.write_text(json.dumps(state))
  status=json.loads(self.run_control('status',ok=True).stdout)
  self.assertEqual(status['runtime'],state)
  out=json.loads(self.run_control('runtime-set','uid-gating','1','5',ok=True).stdout)
  self.assertEqual((out['enabled'],out['generation']),(1,6))
 def test_full_unsigned_generation_range_is_supported(self):
  for generation in (2147483647,2147483648,3999999999,4000000000,4294967294):
   state=json.loads(self.state.read_text());state.update(enabled=0,generation=generation);self.state.write_text(json.dumps(state))
   status=json.loads(self.run_control('status',ok=True).stdout)
   self.assertEqual(status['runtime']['generation'],generation)
   out=json.loads(self.run_control('runtime-set','unicode-filter','1',str(generation),ok=True).stdout)
   self.assertEqual((out['enabled'],out['generation']),(4,generation+1))
 def test_invalid_masks_and_unsigned_generations_are_unavailable(self):
  baseline=json.loads(self.state.read_text())
  for field,value in [('supported',16),('supported',4294967295),('enabled',4294967295),('generation',0),('generation',4294967296)]:
   state=dict(baseline);state[field]=value;self.state.write_text(json.dumps(state))
   self.assertIsNone(json.loads(self.run_control('status',ok=True).stdout)['runtime'])
   self.run_control('runtime-set','uid-gating','1','12',ok=False)
  self.assertEqual(self.writes(),[])
 def test_stale_generation_rejected_before_set(self):
  self.run_control('runtime-set','uid-gating','0','11',ok=False);self.assertEqual(self.writes(),[])
 def test_unsupported_bit_rejected(self):
  state=json.loads(self.state.read_text());state.update(supported=1,enabled=1);self.state.write_text(json.dumps(state))
  self.run_control('runtime-set','hidden-name','0','12',ok=False);self.assertEqual(self.writes(),[])
 def test_bad_abi_rejected(self):
  self.env['MOCK_BAD_ABI']='1';self.run_control('runtime-set','uid-gating','0','12',ok=False);self.assertEqual(self.writes(),[])
 def test_failed_set_does_not_persist(self):
  self.env['MOCK_RUNTIME_FAIL']='1';self.run_control('runtime-set','uid-gating','0','12',ok=False);self.assertFalse((self.persistent/'runtime-options').exists())
 def test_bad_readback_does_not_claim_saved(self):
  self.env['MOCK_BAD_READBACK']='1';self.run_control('runtime-set','uid-gating','0','12',ok=False);self.assertFalse((self.persistent/'runtime-options').exists())
 def test_unknown_version_blocks_every_legacy_write(self):
  for version in ['v2.5.0','v2.4.1','v2.4.0-extra','garbage','']:
   self.env['MOCK_VERSION']=version
   self.run_control('legacy','set_uname','default','default',ok=False)
  self.assertEqual(self.writes(),[])
 def test_230_and_240_legacy_features_remain_available(self):
  for version in ['v2.3.0','v2.4.0']:
   self.env['MOCK_VERSION']=version
   self.run_control('legacy','add_sus_path','/data/adb/example',ok=True)
   self.run_control('legacy','show','enabled_features',ok=True)
  self.assertEqual(len(self.writes()),2)
 def test_unknown_legacy_command_is_not_dispatched(self):
  self.run_control('legacy','arbitrary-shell-command','x',ok=False);self.assertEqual(self.writes(),[])
 def test_ambiguous_zeromount_configuration_is_not_treated_as_off(self):
  for text in ['[susfs]\nenabled=false\nenabled=true\n','[susfs]\nenabled=false\n[susfs]\nenabled=false\n','[susfs]\nenabled="false"\n']:
   (self.zm/'config.toml').write_text(text)
   self.run_control('runtime-set','uid-gating','0','12',ok=False)
  self.assertEqual(self.writes(),[])
 def test_owner_conflicts_prevent_new_and_legacy_writers(self):
  for conflict in ['owner','master','config','other-module','disabled','removed','owner-missing']:
   with self.subTest(conflict=conflict):
    owner=self.zm/'susfs-owner';master=self.zm/'switches/susfs.enabled';config=self.zm/'config.toml'
    owner.write_text('ReSuSFS\n');master.write_text('false\n');config.write_text('[susfs]\nenabled=false\n')
    for flag in ['disable','remove']:(self.mod/flag).unlink(missing_ok=True)
    other=self.phone/'data/adb/modules/susfs4ksu'
    if other.exists():other.rmdir()
    if conflict=='owner':owner.write_text('ZeroMount\n')
    if conflict=='master':master.write_text('true\n')
    if conflict=='config':config.write_text('[susfs]\nenabled=true\n')
    if conflict=='other-module':other.mkdir()
    if conflict=='disabled':(self.mod/'disable').touch()
    if conflict=='removed':(self.mod/'remove').touch()
    if conflict=='owner-missing':owner.unlink()
    self.run_control('runtime-set','uid-gating','0','12',ok=False)
    self.run_control('legacy','set_cmdline_or_bootconfig','file',ok=False)
    self.run_control('priority-set','com.example.app','none',ok=False)
  self.assertEqual(self.writes(),[])
 def test_priority_apply_has_saved_revision_and_honest_readback(self):
  result=json.loads(self.run_control('priority-set','com.example.app,org.example.tool','none',ok=True).stdout)
  self.assertFalse(result['kernel_readback_available']);self.assertTrue(result['saved'])
  self.assertEqual((self.persistent/'priority-packages').read_text(),'com.example.app,org.example.tool\n')
  self.run_control('priority-set','com.other.app','none',ok=False)
  self.assertEqual(len(self.writes()),1)
 def test_priority_clear_uses_official_empty_items_parser(self):
  self.run_control('priority-set','','none',ok=True)
  self.assertEqual(self.writes()[0],['susfs','set_priority_uid_filter',','])
  self.assertEqual((self.persistent/'priority-packages').read_text(),'\n')
 def test_priority_validation_and_feature_gate(self):
  for value in ['com.good;id','com.good\ncom.other','com.good,,com.other','/data/adb','$(id)','com.example.']:
   self.run_control('priority-set',value,'none',ok=False)
  self.env['MOCK_PRIORITY']='no';self.run_control('priority-set','com.example.app','none',ok=False)
  self.assertEqual(self.writes(),[])
 def test_priority_error_does_not_overwrite_saved_choice(self):
  self.env['MOCK_TOOL_FAIL']='1';self.run_control('priority-set','com.example.app','none',ok=False)
  self.assertFalse((self.persistent/'priority-packages').exists())
 def test_boot_without_new_selections_does_not_enable_anything(self):
  self.run_control('restore','runtime',ok=True);self.run_control('restore','priority',ok=True);self.assertEqual(self.writes(),[])
 def test_boot_restores_only_explicit_choices_and_respects_owner(self):
  (self.persistent/'runtime-options').write_text('hidden-name=0\n')
  self.run_control('restore','runtime',ok=True);self.assertEqual(json.loads(self.state.read_text())['enabled'],13)
  self.calls.write_text('');(self.zm/'switches/susfs.enabled').write_text('true\n')
  self.run_control('restore','runtime',ok=False);self.assertEqual(self.writes(),[])
 def test_shell_syntax(self):
  for name in ['resusfs-control','resusfs-susfs','customize.sh']:
   p=subprocess.run(['sh','-n',str(HERE/name)],capture_output=True,text=True);self.assertEqual(p.returncode,0,p.stderr)

class PackageTests(unittest.TestCase):
 def test_official_source_hashes_and_feature_command(self):
  source=json.loads((HERE/'SOURCE.json').read_text())
  self.assertEqual(source['pin'],'a2165b6f875b73e2f87d3c6f12814efac8de061d')
  for name,digest in source['source_files_sha256'].items():self.assertEqual(hashlib.sha256((HERE/'upstream'/name).read_bytes()).hexdigest(),digest)
  self.assertIn('set_priority_uid_filter',(HERE/'upstream/main.c').read_text())
 def test_baseline_contains_no_phone_configuration(self):
  base=json.loads((HERE/'BASE.json').read_text());self.assertFalse(base['device_config_log_key_files_included'])
  with zipfile.ZipFile(HERE/'module-base.zip') as z:
   self.assertIsNone(z.testzip())
   for name in z.namelist():
    self.assertFalse(name.startswith('data/'));self.assertNotIn('.log',name);self.assertNotIn('.key',name)

if __name__=='__main__':unittest.main()
