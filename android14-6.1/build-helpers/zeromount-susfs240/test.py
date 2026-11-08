#!/usr/bin/env python3
"""Exact artifact/mutation checks bound to the actual Android native gate tests."""
from pathlib import Path
import hashlib,json,struct,tempfile,unittest,zipfile,subprocess,sys
import apply as patch
HERE=Path(__file__).resolve().parent
sys.dont_write_bytecode=True

class CompatibilityTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  package=HERE.parent/'zeromount-package-41165'
  base=json.loads((package/'BASE.json').read_text())
  archive=(package/'module-base.zip').read_bytes()
  assert hashlib.sha256(archive).hexdigest()==base['sha256']
  with zipfile.ZipFile(package/'module-base.zip') as z:cls.original=z.read('bin/arm64-v8a/zm-native-core')
  cls.proof=json.loads((HERE/'VERIFICATION.json').read_text())
  cls.updated,cls.receipt=patch.apply(cls.original)

 def test_exact_device_verified_output(self):
  self.assertEqual(patch.sha(self.original),self.proof['original_sha256'])
  self.assertEqual(patch.sha(self.updated),self.proof['patched_sha256'])
  self.assertEqual(patch.sha(self.updated),'2144cf2f40f3f8a5dd41e848a56047598cc6307165a6ae084107bd6f833b3d91')

 def test_only_five_audited_bytes_changed(self):
  differences=[i for i,(a,b) in enumerate(zip(self.original,self.updated)) if a!=b]
  self.assertEqual(differences,[323960,373214,547836,1822017,1822044])
  self.assertEqual(len(self.original),len(self.updated))
  normalized=bytearray(self.updated)
  for i in differences:normalized[i]=self.original[i]
  self.assertEqual(bytes(normalized),self.original)

 def test_instruction_registers_shifts_and_control_flow_preserved(self):
  for offset,(before,after) in patch.WORDS.items():
   old=struct.unpack_from('<I',self.original,offset)[0]
   new=struct.unpack_from('<I',self.updated,offset)[0]
   self.assertEqual((old,new),(before,after))
   self.assertEqual(old&~0x1fffe0,new&~0x1fffe0)
  self.assertEqual(patch.expected_versions(self.original),[b'v2.3.0',b'2.3.0'])
  self.assertEqual(patch.expected_versions(self.updated),[b'v2.4.0',b'2.4.0'])
  self.assertEqual(patch.sections(self.original),patch.sections(self.updated))

 def test_unknown_inputs_fail_closed(self):
  for offset in [18,323960,0x1bcd40,0x1bcd5c,len(self.original)-1]:
   changed=bytearray(self.original);changed[offset]^=1
   with self.assertRaises(RuntimeError):patch.apply(bytes(changed))
  with self.assertRaises(RuntimeError):patch.apply(self.updated)

 def test_literal_decoder_rejects_changed_instruction_semantics(self):
  changed=bytearray(self.original)
  struct.pack_into('<I',changed,0x1bcd40,patch.WORDS[0x1bcd40][0]^1)
  with self.assertRaises(RuntimeError):patch.expected_versions(bytes(changed))

 def test_actual_android_positive_negative_matrix_and_read_abi(self):
  cases=self.proof['cases'];self.assertEqual(len(cases),7)
  expected={('original','v2.3.0'):True,('original','v2.4.0'):False,('original','v2.5.0'):False,
            ('patched','v2.4.0'):True,('patched','v2.3.0'):False,('patched','v2.5.0'):False,('patched','2.4.0'):True}
  features=None
  for case in cases:
   key=case['binary'],case['simulated_version_response'];report=case['native_report'];trace=case['trace']
   supported=expected.pop(key)
   self.assertEqual(report['abi_supported'],supported)
   self.assertEqual((case['adb_exit'],trace['exit']),(0,0) if supported else (1,1))
   self.assertEqual(report['kernel_reported_version'],key[1])
   self.assertEqual((report['path_size'],report['kstat_size'],report['kstat_flags_offset'],report['kstat_error_offset']),(260,376,368,372))
   self.assertEqual((trace['version_queries'],trace['feature_queries'],trace['denied_mutations']),(1,1,0))
   self.assertEqual(len(report['features']),14)
   if features is None:features=report['features']
   self.assertEqual(features,report['features'])
  self.assertFalse(expected)
  self.assertEqual(self.proof['susfs_kernel_write_calls_executed'],0)
  self.assertFalse(self.proof['full_240_kernel_boot_tested'])

 def test_cli_preserves_original_and_refuses_unrelated_output(self):
  with tempfile.TemporaryDirectory() as directory:
   root=Path(directory);source=root/'source';target=root/'patched';receipt=root/'receipt.json'
   source.write_bytes(self.original)
   result=subprocess.run([sys.executable,'-B',str(HERE/'apply.py'),str(source),str(target),'--receipt',str(receipt)],capture_output=True)
   self.assertEqual(result.returncode,0,result.stderr)
   self.assertEqual(source.read_bytes(),self.original);self.assertEqual(target.read_bytes(),self.updated)
   target.write_bytes(b'unrelated')
   result=subprocess.run([sys.executable,'-B',str(HERE/'apply.py'),str(source),str(target),'--receipt',str(receipt)],capture_output=True)
   self.assertNotEqual(result.returncode,0);self.assertEqual(target.read_bytes(),b'unrelated')

if __name__=='__main__':unittest.main()
