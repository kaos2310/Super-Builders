#!/usr/bin/env python3
"""Verify a concrete flash ZIP, including the real installer/dispatcher in fixtures."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,tempfile,unittest,zipfile
sys.dont_write_bytecode=True
from test import MOCK_TOOL,MOCK_RUNTIME
HERE=Path(__file__).resolve().parent
ZIP=Path(sys.argv.pop(1)).resolve()

class FlashZipTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  with zipfile.ZipFile(ZIP) as z:
   assert z.testzip() is None;cls.members={n:z.read(n) for n in z.namelist()}
  with zipfile.ZipFile(HERE/'module-base.zip') as z:cls.baseline={n:z.read(n) for n in z.namelist()}
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
  self.mod=self.root/'module';self.mod.mkdir();self.phone=self.root/'phone';self.phone.mkdir()
  for name,data in self.members.items():
   p=self.mod/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
   if name.startswith('bin/') or name.endswith('.sh'):p.chmod(0o755)
  self.persistent=self.phone/'data/adb/ReSuSFS'
  self.tool=self.root/'tool';self.tool.write_text(MOCK_TOOL);self.tool.chmod(0o755)
  self.calls=self.root/'calls';self.calls.write_text('')
  self.env=dict(os.environ,MOCK_CALLS=str(self.calls))
 def installer(self,version='v2.4.0'):
  # Only the fixture's persistent prefix changes; production script is executed.
  script=self.members['customize.sh'].decode().replace('PERSISTENT_DIR=/data/adb/ReSuSFS','PERSISTENT_DIR='+str(self.persistent))
  p=self.mod/'bin/ksu_susfs';p.write_text(MOCK_TOOL);p.chmod(0o755)
  harness=self.root/'install.sh';harness.write_text('''#!/bin/sh
ui_print() { :; }
abort() { echo "$*" >&2;exit 1; }
set_perm_recursive() { :; }
set_perm() { :; }
getprop() { echo arm64-v8a; }
'''+script)
  return subprocess.run(['sh',str(harness)],capture_output=True,text=True,env=dict(self.env,KSU='true',MODPATH=str(self.mod),MOCK_VERSION=version))
 def test_all_zip_checksums(self):
  for line in self.members['SHA256SUMS'].decode().splitlines():
   digest,name=line.split('  ',1);self.assertEqual(hashlib.sha256(self.members[name]).hexdigest(),digest,name)
 def test_r2_version_and_android_proof_match_packaged_controller(self):
  self.assertIn(b'versionCode=2026110901\n',self.members['module.prop'])
  self.assertIn(b'runtime1.r2.',self.members['module.prop'])
  proof=json.loads(self.members['verification/ANDROID-SETTER-PROOF.json'])
  self.assertEqual(proof['controller_sha256'],hashlib.sha256(self.members['bin/resusfs-control']).hexdigest())
  self.assertEqual({case['key'] for case in proof['cases']},{'uid-gating','hidden-name','unicode-filter','symbol-hiding'})
  self.assertTrue(all(case['flipped_and_read_back'] and case['persisted_choice_verified'] and case['restored_original_bit'] for case in proof['cases']))
 def test_addition_is_separate_and_both_original_action_buttons_remain(self):
  module=self.members['webroot/assets/resusfs-runtime.mjs'].decode()
  self.assertIn("doc.createElement('dialog')",module)
  self.assertIn("opener.textContent='Runtime & Priority UID",module)
  css=self.members['webroot/assets/resusfs-runtime.css'].decode()
  self.assertNotIn('force-update',css)
  self.assertNotIn('.command',css)
  self.assertIn(b'resusfs-runtime.mjs?r=2',self.members['webroot/index.html'])
 def test_old_config_scripts_styles_cron_and_missing_choices_preserved(self):
  files={'config.txt':b'CUSTOM_USER_VALUE=keep\n','sus_paths.txt':b'/my/custom/path\n','scripts/my-script.sh':b'echo untouched\n','scripts_cron.txt':b'1 * * * * my-script.sh\n','.webui_config/custom.css':b':root{--custom:keep}\n','crontabs/root':b'user crontab\n'}
  for name,data in files.items():p=self.persistent/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
  before={p.relative_to(self.persistent).as_posix():p.read_bytes() for p in self.persistent.rglob('*') if p.is_file()}
  result=self.installer();self.assertEqual(result.returncode,0,result.stderr)
  self.assertEqual(before,{p.relative_to(self.persistent).as_posix():p.read_bytes() for p in self.persistent.rglob('*') if p.is_file()})
  self.assertFalse((self.persistent/'runtime-options').exists());self.assertFalse((self.persistent/'priority-packages').exists())
 def test_fresh_install_has_original_defaults_style_and_private_alias(self):
  result=self.installer();self.assertEqual(result.returncode,0,result.stderr)
  for name,data in self.baseline.items():
   if name.startswith('configs/'):
    self.assertEqual((self.persistent/name.removeprefix('configs/')).read_bytes(),data,name)
  self.assertEqual((self.persistent/'.webui_config/custom.css').read_bytes(),self.baseline['custom.css'])
  self.assertIn('bin/ReSuSFS',self.members)
  self.assertIn('PATH=/data/adb/modules/ReSuSFS/bin:',self.members['ReSuSFS.sh'].decode())
 def test_unknown_kernel_installer_rejected_before_config_creation(self):
  result=self.installer('v2.5.0');self.assertNotEqual(result.returncode,0);self.assertFalse(self.persistent.exists())
 def test_original_ui_rule_editors_defaults_and_translations_retained(self):
  for name,data in self.baseline.items():
   if name.startswith('configs/') or name.startswith('webroot/locales/') or (name.startswith('webroot/assets/index-') and name.endswith(('.js','.css'))):
    self.assertEqual(self.members[name],data,name)
 def test_existing_userhub_and_cron_dispatchers_pause_when_owner_changes(self):
  mods=self.phone/'data/adb/modules';(mods/'ReSuSFS').mkdir(parents=True);(mods/'meta-zeromount').mkdir()
  zm=self.phone/'data/adb/zeromount';(zm/'switches').mkdir(parents=True)
  (zm/'susfs-owner').write_text('ZeroMount\n');(zm/'switches/susfs.enabled').write_text('true\n');(zm/'config.toml').write_text('[susfs]\nenabled=true\n')
  # Rebase absolute module paths only inside this host test fixture.
  for p in self.mod.rglob('*'):
   if p.is_file() and (p.suffix=='.sh' or p.parent==self.mod/'bin'):
    data=p.read_bytes()
    if data.startswith(b'#!'):
     text=data.decode().replace('#!/system/bin/sh','#!/bin/sh').replace('/data/adb/modules/ReSuSFS',str(self.mod)).replace('/data/adb/ReSuSFS',str(self.persistent));p.write_text(text);p.chmod(0o755)
  danger=self.root/'danger.sh';marker=self.root/'mutated';danger.write_text('echo changed > '+str(marker)+'\n')
  env=dict(self.env,RESUSFS_ROOT=str(self.phone),RESUSFS_MODDIR=str(self.mod),RESUSFS_SUSFS_TOOL=str(self.tool))
  for args in [['--action'],['--stage-early'],['--stage-late'],['--run-postfs-scripts'],['--run-bootcompleted-scripts'],['--sync-cron-scripts'],['--run-script',str(danger)]]:
   result=subprocess.run(['sh',str(self.mod/'ReSuSFS.sh'),*args],capture_output=True,text=True,env=env)
   self.assertNotEqual(result.returncode,0,args)
  result=subprocess.run(['sh',str(self.mod/'post-fs-data.sh')],capture_output=True,text=True,env=env)
  self.assertNotEqual(result.returncode,0,'post-fs-data owner guard must precede LKM loader')
  self.assertFalse(marker.exists());self.assertFalse(self.persistent.exists())
  self.assertEqual(self.calls.read_text(),'')
  result=subprocess.run(['sh',str(self.mod/'ReSuSFS.sh'),'--force-update'],capture_output=True,text=True,env=env)
  self.assertEqual(result.returncode,0,result.stderr);self.assertFalse(json.loads(result.stdout)['write_allowed'])
  self.assertTrue(all(call[0]=='susfs' and call[1]=='show' for call in map(json.loads,self.calls.read_text().splitlines())))
 def test_uninstall_does_not_delete_external_files(self):
  marker=self.root/'global-tool';marker.write_bytes(b'keep')
  result=subprocess.run(['sh',str(self.mod/'uninstall.sh')],capture_output=True,text=True)
  self.assertEqual(result.returncode,0);self.assertEqual(marker.read_bytes(),b'keep')
  self.assertNotIn(b'rm -f /data/adb/ksu/bin',self.members['uninstall.sh'])
 def test_every_packaged_shell_has_valid_syntax(self):
  for name,data in self.members.items():
   if name.endswith('.sh') or name in ('bin/resusfs-control','bin/resusfs-susfs','bin/ReSuSFS'):
    p=self.mod/name;result=subprocess.run(['sh','-n',str(p)],capture_output=True,text=True);self.assertEqual(result.returncode,0,name+result.stderr)

if __name__=='__main__':unittest.main()
