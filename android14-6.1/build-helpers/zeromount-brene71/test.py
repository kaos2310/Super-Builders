#!/usr/bin/env python3
"""Exercise the delivered adapter with mocked Android commands, never the phone."""
from pathlib import Path
import subprocess, tempfile, os, json, unittest, sys
HERE=Path(__file__).resolve().parent
class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.bin=self.root/'bin';self.bin.mkdir();self.log=self.root/'calls'
        self.env=dict(os.environ,PATH=str(self.bin)+':'+os.environ['PATH'],ZM71_STATE=str(self.root/'state'),ZM71_NATIVE=str(self.bin/'native'),ZM71_RESETPROP=str(self.bin/'rp'),ZM71_KSUD=str(self.bin/'ksud'),ZM71_EXTERNAL_FLAG=str(self.root/'external'),TEST_LOG=str(self.log),TEST_BOOT='1',TEST_DATE='2026 10 18',TEST_MASTER='true',TEST_OS='true',TEST_VENDOR='true',TEST_NATIVE_RC='0')
        scripts={
         'getprop':'echo "$TEST_BOOT"',
         'date':'echo "$TEST_DATE"',
         'native':'''if [ "$1" = config ]; then
case "$3" in brene.prop_spoofing) echo "$TEST_MASTER";; brene.spoof_os_security_patch_level_property) echo "$TEST_OS";; brene.spoof_vendor_security_patch_level_property) echo "$TEST_VENDOR";; *) exit 64;; esac
else printf 'native:%s\\n' "$*" >> "$TEST_LOG"; exit "$TEST_NATIVE_RC"; fi''',
         'rp':'''if [ "$#" -eq 1 ]; then echo old; else printf 'rp:%s\\n' "$*" >> "$TEST_LOG"; fi''',
         'ksud':'''printf 'ksud:%s\\n' "$*" >> "$TEST_LOG"; if [ "$3" = version ]; then echo "${TEST_SUSFS_VERSION:-v2.3.0}"; elif [ "$3" = enabled_features ]; then echo "${TEST_FEATURES:-CONFIG_KSU_SUSFS_OPEN_REDIRECT}"; fi''',
         'logcat':'printf "logcat:%s\\n" "$*" >> "$TEST_LOG"',
        }
        for name,body in scripts.items():
            p=self.bin/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
    def tearDown(self):self.tmp.cleanup()
    def run_adapter(self,*args,ok=True,**env):
        p=subprocess.run(['sh',str(HERE/'zm-brene71'),*args],env={**self.env,**env},text=True,capture_output=True)
        if ok:self.assertEqual(p.returncode,0,p.stderr)
        else:self.assertNotEqual(p.returncode,0)
        return p
    def calls(self):return self.log.read_text() if self.log.exists() else ''
    def test_status_is_read_only(self):
        report=json.loads(self.run_adapter('status').stdout)
        self.assertEqual(report['version'],'0.0.71');self.assertFalse((self.root/'state').exists());self.assertEqual(self.calls(),'')
        self.assertEqual(report['settings']['values']['shrink_buffer_size'],'true')
    def test_roundtrip_each_option(self):
        for key in ('shrink_buffer_size','spoof_hosts','spoof_libstagefright','hide_lineage_strings','disable_child_process_restrictions'):
            self.run_adapter('set',key,'true');self.assertEqual(self.run_adapter('get',key).stdout.strip(),'true')
            self.run_adapter('set',key,'false');self.assertEqual(self.run_adapter('get',key).stdout.strip(),'false')
    def test_reject_unknown_and_injection(self):
        for key in ('x','../options','$(touch BAD)','shrink_buffer_size;exit'):
            self.run_adapter('set',key,'true',ok=False)
        self.run_adapter('set','shrink_buffer_size','1',ok=False);self.assertFalse((self.root/'state').exists())
    def test_corrupt_config_rejected(self):
        (self.root/'state').mkdir();(self.root/'state/options').write_text('shrink_buffer_size=maybe\n')
        self.run_adapter('status',ok=False);self.run_adapter('set','spoof_hosts','true',ok=False)
        self.assertFalse((self.root/'state/config.lock').exists())
    def test_lock_prevents_lost_update(self):
        (self.root/'state/config.lock').mkdir(parents=True)
        self.assertEqual(self.run_adapter('set','spoof_hosts','true',ok=False).returncode,75)
    def test_month_boundaries(self):
        for date,want in [('2026 08 04','2026-07'),('2026 08 05','2026-08'),('2026 09 01','2026-08'),('2026 09 05','2026-09'),('2026 01 01','2025-12'),('2026 12 31','2026-12')]:
            self.assertEqual(self.run_adapter('patch-month',TEST_DATE=date).stdout.strip(),want)
    def test_invalid_clock_rejected_before_native(self):
        for date in ('1970 01 01','2026 00 12','2026 13 01','2026 09 00','2026 09 32','2026 08 08 junk','bad date','2026 0x 02'):
            self.run_adapter('prop-watch',ok=False,TEST_DATE=date)
        self.assertEqual(self.calls(),'')
    def test_early_writer_deferred(self):
        self.run_adapter('prop-watch',TEST_BOOT='0');self.assertEqual(self.calls(),'')
    def test_late_pipeline_native_first_and_correct_month(self):
        self.run_adapter('prop-watch',TEST_DATE='2026 01 04')
        calls=self.calls();self.assertTrue(calls.startswith('native:prop-watch\n'))
        self.assertIn('ro.build.version.security_patch 2025-12-01',calls);self.assertIn('ro.vendor.build.security_patch 2025-12-05',calls)
        self.assertIn('ro.crypto.state encrypted',calls)
    def test_group_opt_outs(self):
        self.run_adapter('prop-watch',TEST_OS='false',TEST_VENDOR='false')
        self.assertNotIn('security_patch',self.calls())
    def test_master_opt_out(self):
        self.run_adapter('prop-watch',TEST_MASTER='false');self.assertNotIn('rp:',self.calls())
    def test_external_owner_respected(self):
        (self.root/'external').write_text('brene\n');self.run_adapter('prop-watch');self.assertNotIn('rp:',self.calls())
    def test_native_error_propagated(self):
        self.assertEqual(self.run_adapter('prop-watch',ok=False,TEST_NATIVE_RC='42').returncode,42);self.assertNotIn('rp:',self.calls())
    def test_late_default_buffer(self):
        self.run_adapter('late');self.assertIn('logcat:-G 64K',self.calls());self.assertIn('persist.logd.size 65536',self.calls());self.assertNotIn('ksud:',self.calls())
    def test_late_early_does_nothing(self):
        self.run_adapter('late',ok=False,TEST_BOOT='0');self.assertEqual(self.calls(),'');self.assertFalse((self.root/'state').exists())
    def test_late_buffer_optout_and_phantom_optin(self):
        self.run_adapter('set','shrink_buffer_size','false');self.run_adapter('set','disable_child_process_restrictions','true');self.run_adapter('late')
        self.assertNotIn('logcat:',self.calls());self.assertIn('settings_enable_monitor_phantom_procs false',self.calls())
    def test_redirect_version_and_feature_gate(self):
        self.run_adapter('set','spoof_hosts','true')
        for env in ({'TEST_SUSFS_VERSION':'v2.2.0'},{'TEST_FEATURES':'CONFIG_KSU_SUSFS_SUS_PATH'}):
            self.run_adapter('late',ok=False,**env)
        self.assertNotIn('add_open_redirect',self.calls());self.assertFalse((self.root/'state/fake-files').exists())
    def test_cli_rejects_extra_arguments(self):
        for args in (('status','x'),('get','spoof_hosts','x'),('set','spoof_hosts','true','x'),('prop-watch','--unknown'),('late','x')):
            self.run_adapter(*args,ok=False)
if __name__=='__main__':unittest.main()
