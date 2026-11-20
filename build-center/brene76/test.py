#!/usr/bin/env python3
"""Exercise the delivered adapter with mocked Android commands, never the phone."""
from pathlib import Path
import subprocess, tempfile, os, json, unittest, sys, ast
import shutil
HERE=Path(__file__).resolve().parent
SHELL=shutil.which('sh') or (r'C:\Program Files\Git\bin\sh.exe' if os.name=='nt' else 'sh')
def posix(value):
    value=str(value).replace('\\','/')
    return '/'+value[0].lower()+value[2:] if len(value)>2 and value[1]==':' else value
def shell_env(env):
    if os.name!='nt':return env
    result={k:posix(v) if isinstance(v,str) and len(v)>2 and v[1]==':' else v for k,v in env.items()}
    result['PATH']=posix(env['ZM71_NATIVE'].rsplit('\\',1)[0])+':/usr/bin:/bin'
    return result
class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.bin=self.root/'bin';self.bin.mkdir();self.log=self.root/'calls'
        self.env=dict(os.environ,PATH=str(self.bin)+':'+os.environ['PATH'],ZM71_STATE=str(self.root/'state'),ZM71_NATIVE=str(self.bin/'native'),ZM71_RESETPROP=str(self.bin/'rp'),ZM71_KSUD=str(self.bin/'ksud'),ZM71_EXTERNAL_FLAG=str(self.root/'external'),TEST_LOG=str(self.log),TEST_BOOT='1',TEST_DATE='2026 10 18',TEST_MASTER='true',TEST_OS='true',TEST_VENDOR='true',TEST_NATIVE_RC='0')
        self.env.update(ZM76_OWNER=str(self.bin/'owner'),ZM76_SUSFS_TOOL=str(self.bin/'susfs'),ZM76_PACKAGES_LIST=str(self.root/'packages.list'),ZM76_MODULES_ROOT=str(self.root/'modules'))
        scripts={
         'owner':'[ "$1" = allowed ] || exit 64; case "$2" in brene) [ "${TEST_BRENE:-true}" = true ];; susfs) [ "${TEST_SUSFS:-true}" = true ] && [ "${TEST_EXTERNAL:-false}" = false ];; *) exit 64;; esac',
         'susfs':'printf \'susfs:%s\\n\' "$*" >> "$TEST_LOG"; [ "$1" = set_sus_path_uid_filter ] && [ "$#" = 2 ] || exit 64; exit "${TEST_TOOL_RC:-0}"',
         'getprop':'echo "$TEST_BOOT"',
         'date':'echo "$TEST_DATE"',
         'native':'''if [ "$1" = config ]; then
case "$3" in brene.prop_spoofing) echo "$TEST_MASTER";; brene.spoof_os_security_patch_level_property) echo "$TEST_OS";; brene.spoof_vendor_security_patch_level_property) echo "$TEST_VENDOR";; *) exit 64;; esac
else printf 'native:%s\\n' "$*" >> "$TEST_LOG"; exit "$TEST_NATIVE_RC"; fi''',
         'rp':'''if [ "$#" -eq 1 ]; then echo old; else printf 'rp:%s\\n' "$*" >> "$TEST_LOG"; fi''',
         'ksud':'''[ -z "${SUKISU_CLI_PARSER:-}" ] || "$SUKISU_CLI_PARSER" "$@" || exit $?
printf 'ksud:%s\\n' "$*" >> "$TEST_LOG"
case "$1:$2:$#" in
susfs:version:2) printf '%s\\n' "${TEST_SUSFS_VERSION-v2.4.0}"; exit "${TEST_VERSION_RC:-0}";;
susfs:features:2) printf '%s\\n' "${TEST_FEATURES-CONFIG_KSU_SUSFS_OPEN_REDIRECT}"; exit "${TEST_FEATURES_RC:-0}";;
susfs:add-open-redirect:5) exit 0;;
susfs:add-sus-path-loop:3) exit 0;;
susfs:add-sus-map:3) exit 0;;
susfs:set-priority-uid-filter:3) exit 0;;
*) echo 'unrecognized SukiSU command' >&2; exit 2;;
esac''',
         'logcat':'printf "logcat:%s\\n" "$*" >> "$TEST_LOG"',
         'cmd':'[ "$*" = "package list packages -3" ] || exit 64; printf "%s\\n" "${TEST_PACKAGES-}"; exit "${TEST_PACKAGES_RC:-0}"',
         'chcon':'exit 0',
         'chown':'exit 0',
        }
        for name,body in scripts.items():
            p=self.bin/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
    def tearDown(self):self.tmp.cleanup()
    def run_adapter(self,*args,ok=True,**env):
        p=subprocess.run([SHELL,posix(HERE/'zm-brene76'),*args],env=shell_env({**self.env,**env}),text=True,capture_output=True)
        if ok:self.assertEqual(p.returncode,0,p.stderr)
        else:self.assertNotEqual(p.returncode,0)
        return p
    def calls(self):return self.log.read_text() if self.log.exists() else ''
    def test_status_is_read_only(self):
        report=json.loads(self.run_adapter('status').stdout)
        self.assertEqual(report['version'],'0.0.76');self.assertFalse((self.root/'state').exists());self.assertEqual(self.calls(),'')
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
    def test_feature_query_error_cannot_enable_redirects(self):
        self.run_adapter('set','spoof_hosts','true')
        for env in ({'TEST_VERSION_RC':'42'},{'TEST_FEATURES_RC':'42'}):
            self.run_adapter('late',ok=False,**env)
        self.assertNotIn('add-open-redirect',self.calls())
    def test_feature_lines_are_normalized_without_substring_acceptance(self):
        self.run_adapter('set','spoof_hosts','true')
        self.run_adapter('late',ok=False,TEST_FEATURES='CONFIG_KSU_SUSFS_OPEN_REDIRECT_FAKE')
        self.assertFalse((self.root/'state/fake-files').exists())
    def run_function(self,code,args=(),**env):
        source=(HERE/'zm-brene76').read_text().split('case "${1:-status}" in')[0]
        return subprocess.run([SHELL,'-c',source+'\n'+code,'adapter-test',*map(posix,args)],env=shell_env({**self.env,**env}),capture_output=True,text=True)
    def test_real_feature_formats_accepted(self):
        for features in ('CONFIG_KSU_SUSFS_SUS_PATH\nCONFIG_KSU_SUSFS_OPEN_REDIRECT\n','CONFIG_KSU_SUSFS_SUS_PATH,CONFIG_KSU_SUSFS_OPEN_REDIRECT',' CONFIG_KSU_SUSFS_SUS_PATH, CONFIG_KSU_SUSFS_OPEN_REDIRECT\r\n'):
            result=self.run_function('require_open_redirect',TEST_FEATURES=features)
            self.assertEqual(result.returncode,0,result.stderr)
    def test_redirect_calls_actual_sukisu_spelling(self):
        target=self.root/'target file';replacement=self.root/'replacement file'
        target.write_text('original');replacement.write_text('replacement')
        result=self.run_function('redirect_file "$1" "$2"',(target,replacement))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('ksud:susfs add-open-redirect',self.calls())
        self.assertNotIn('add_open_redirect',self.calls())
    def test_new_options_preserve_old_values(self):
        self.run_adapter('set','spoof_hosts','true')
        for key in ('hide_ksu_directories','hide_third_party_apps'):
            self.assertEqual(self.run_adapter('get',key).stdout.strip(),'false')
            self.run_adapter('set',key,'true')
        self.assertEqual(self.run_adapter('get','spoof_hosts').stdout.strip(),'true')
    def test_directory_view_keeps_termux_and_hma_data(self):
        storage=self.root/'Android'
        for package in ('com.termux','org.frknkrc44.hma_oss'):
            path=storage/'data'/package;path.mkdir(parents=True);(path/'valuable').write_text('keep')
        self.run_adapter('set','hide_ksu_directories','true')
        self.run_adapter('late',ZM75_STORAGE_ROOT=str(storage),TEST_FEATURES='CONFIG_KSU_SUSFS_SUS_PATH')
        self.assertEqual(len(list(storage.rglob('valuable'))),2)
        self.assertEqual(self.calls().count('ksud:susfs add-sus-path-loop'),2)
    def test_priority_filter_has_exact_feature_gate(self):
        self.run_adapter('set','hide_third_party_apps','true')
        for feature in ('CONFIG_KSU_SUSFS_SUS_PATH','CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER_FAKE'):
            self.run_adapter('late',ok=False,TEST_FEATURES=feature)
        self.assertNotIn('ksud:susfs set-priority-uid-filter',self.calls())
    def test_priority_filter_uses_validated_deduplicated_names(self):
        self.run_adapter('set','hide_third_party_apps','true')
        self.run_adapter('late',TEST_FEATURES='CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER',TEST_PACKAGES='package:com.two\npackage:com.one\npackage:com.two')
        self.assertIn('ksud:susfs set-priority-uid-filter com.one,com.two\n',self.calls())
    def test_package_query_failure_does_not_replace_filter(self):
        self.run_adapter('set','hide_third_party_apps','true')
        for value in ('package:com.one\necho bad','package:$(touch BAD)','not-a-package'):
            self.run_adapter('late',ok=False,TEST_FEATURES='CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER',TEST_PACKAGES=value)
        self.run_adapter('late',ok=False,TEST_FEATURES='CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER',TEST_PACKAGES_RC='42')
        self.assertNotIn('ksud:susfs set-priority-uid-filter',self.calls())
    def test_empty_third_party_list_uses_clear_sentinel(self):
        self.run_adapter('set','hide_third_party_apps','true')
        self.run_adapter('late',TEST_FEATURES='CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER',TEST_PACKAGES='')
        self.assertIn('ksud:susfs set-priority-uid-filter ,\n',self.calls())
    def test_new_susfs_mutations_respect_external_owner(self):
        self.run_adapter('set','hide_third_party_apps','true');(self.root/'external').write_text('brene\n')
        self.run_adapter('late',ok=False,TEST_FEATURES='CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER',TEST_PACKAGES='package:com.one')
        self.assertNotIn('ksud:susfs set-priority-uid-filter',self.calls())
    def test_new_flags_default_off_and_keep_inherited_state(self):
        self.run_adapter('set','spoof_hosts','true')
        state=self.root/'state/options'
        with state.open('a') as f:f.write('# keep me\nfuture_key=still-here\n')
        for key in ('hide_all_apps_with_uid_10000_and_above','sus_path_uid_filter','hide_vector_injection'):
            self.assertEqual(self.run_adapter('get',key).stdout.strip(),'false')
            self.run_adapter('set',key,'true')
        self.assertEqual(self.run_adapter('get','spoof_hosts').stdout.strip(),'true')
        self.assertIn('future_key=still-here',state.read_text());self.assertIn('# keep me',state.read_text())
    def test_filter_status_read_only_and_store_does_not_apply(self):
        self.assertEqual(json.loads(self.run_adapter('status').stdout)['sus_path_uid_filter_packages'],',')
        self.assertFalse((self.root/'state').exists());self.assertEqual(self.calls(),'')
        self.run_adapter('filter-set','com.two, com.one,com.two')
        self.assertEqual(self.run_adapter('filter-get').stdout.strip(),'com.two,com.one')
        self.assertEqual(self.calls(),'')
    def test_filter_validated_before_persistence(self):
        for value in ('com.app;touch BAD','$(touch BAD)','com.one\ncom.two','..','.', 'x'*256):
            self.run_adapter('filter-set',value,ok=False)
        self.assertFalse((self.root/'state').exists());self.assertEqual(self.calls(),'')
    def test_filter_enable_uses_private_exact_command_next_boot(self):
        self.run_adapter('filter-set','com.visible')
        self.run_adapter('set','sus_path_uid_filter','true')
        self.assertEqual(self.calls(),'')
        self.run_adapter('late',TEST_FEATURES='CONFIG_KSU_SUSFS_SUS_PATH')
        self.assertIn('susfs:set_sus_path_uid_filter com.visible\n',self.calls())
    def test_filter_empty_list_sends_clear_sentinel(self):
        self.run_adapter('filter-set','')
        self.run_adapter('set','sus_path_uid_filter','true')
        self.run_adapter('late',TEST_FEATURES='CONFIG_KSU_SUSFS_SUS_PATH')
        self.assertIn('susfs:set_sus_path_uid_filter ,\n',self.calls())
    def test_filter_runtime_support_is_not_inferred_from_version(self):
        self.run_adapter('set','sus_path_uid_filter','true')
        self.assertEqual(self.run_adapter('late',ok=False,TEST_FEATURES='CONFIG_KSU_SUSFS_SUS_PATH',TEST_TOOL_RC='95').returncode,95)
        self.assertNotIn('available',self.run_adapter('status').stdout)
    def test_filter_feature_query_failure_does_not_apply(self):
        self.run_adapter('set','sus_path_uid_filter','true')
        for env in ({'TEST_SUSFS_VERSION':'v2.3.0'},{'TEST_FEATURES':'CONFIG_KSU_SUSFS_SUS_PATH_FAKE'},{'TEST_FEATURES_RC':'42'}):
            self.run_adapter('late',ok=False,**env)
        self.assertNotIn('susfs:set_sus_path_uid_filter',self.calls())
    def test_master_pause_blocks_late_without_writes(self):
        for env in ({'TEST_BRENE':'false'},{'TEST_SUSFS':'false'},{'TEST_EXTERNAL':'true'}):
            self.run_adapter('late',ok=False,**env)
        self.assertEqual(self.calls(),'');self.assertFalse((self.root/'state').exists())
    def test_all_app_uid_mode_includes_system_and_overrides_third_party(self):
        (self.root/'packages.list').write_text('com.core 1000 0 /data/a\ncom.systemapp 10000 0 /data/b\ncom.userapp 10234 0 /data/c\ncom.userapp 10234 0 /data/c\n')
        self.run_adapter('set','hide_third_party_apps','true')
        self.run_adapter('set','hide_all_apps_with_uid_10000_and_above','true')
        self.run_adapter('late',TEST_FEATURES='CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER',TEST_PACKAGES='package:com.should_not_win')
        self.assertIn('ksud:susfs set-priority-uid-filter com.systemapp,com.userapp\n',self.calls())
        self.assertNotIn('com.should_not_win',self.calls())
        self.assertEqual(self.run_adapter('get','hide_third_party_apps').stdout.strip(),'true')
    def test_all_app_corrupt_source_never_replaces_priority_filter(self):
        (self.root/'packages.list').write_text('com.ok 10000 0\ncom.bad nope 0\n')
        self.run_adapter('set','hide_all_apps_with_uid_10000_and_above','true')
        self.run_adapter('late',ok=False,TEST_FEATURES='CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER')
        self.assertNotIn('ksud:susfs set-priority-uid-filter',self.calls())
    def test_vector_uses_native_cli_and_preserves_files(self):
        path=self.root/'modules/zygisk_vector/zygisk/arm64-v8a.so';path.parent.mkdir(parents=True);path.write_bytes(b'keep')
        self.run_adapter('set','hide_vector_injection','true')
        self.run_adapter('late',TEST_FEATURES='CONFIG_KSU_SUSFS_SUS_MAP')
        self.assertIn('ksud:susfs add-sus-map ',self.calls());self.assertEqual(path.read_bytes(),b'keep')
    def test_config_corruption_blocks_before_any_property_changes(self):
        self.run_adapter('set','spoof_hosts','false')
        (self.root/'state/options').write_text('spoof_hosts=bad\n')
        self.run_adapter('late',ok=False);self.assertEqual(self.calls(),'')
    def test_filter_config_lock_preserves_saved_value(self):
        self.run_adapter('filter-set','com.old')
        (self.root/'state/config.lock').mkdir()
        self.assertEqual(self.run_adapter('filter-set','com.new',ok=False).returncode,75)
        self.assertEqual(self.run_adapter('filter-get').stdout.strip(),'com.old')
    def test_filter_rejects_injection_and_malformed_persisted_list(self):
        for value in ('com.ok;reboot', "com.ok'", '$(id)', 'com.ok\ncom.other', '.', '..', 'a'*256):
            self.run_adapter('filter-set',value,ok=False)
        self.assertFalse((self.root/'state').exists())
        (self.root/'state').mkdir();(self.root/'state/sus-path-uid-filter').write_text("com.bad'\n")
        self.run_adapter('status',ok=False)
    def test_oem_option_is_additive_and_respects_property_group(self):
        self.run_adapter('set','hide_oem_unlocking_toggle','true')
        self.run_adapter('late',TEST_MASTER='false')
        self.assertNotIn('ro.oem_unlock_supported',self.calls())
        self.run_adapter('late')
        self.assertIn('rp:-n ro.oem_unlock_supported 0',self.calls())
    def test_fingerprint_cleanup_quotes_data_and_keeps_original_setting(self):
        rp=self.bin/'rp'
        rp.write_text('''#!/bin/sh
if [ "$#" = 1 ]; then echo 'lineage/device/product:14/build/1:userdebug/test-keys'; else printf 'rp:%s\\n' "$*" >> "$TEST_LOG"; fi
''',newline='\n');rp.chmod(0o755)
        self.run_adapter('set','sanitize_build_fingerprint','true')
        self.run_adapter('set','spoof_hosts','false')
        self.run_adapter('late')
        self.assertIn('rp:-n ro.build.fingerprint /device/product:14/build/1:user/release-keys',self.calls())
        self.assertEqual(self.run_adapter('get','sanitize_build_fingerprint').stdout.strip(),'true')
        self.assertEqual(self.run_adapter('get','spoof_hosts').stdout.strip(),'false')
    def test_nova_manager_storage_is_included_without_removing_ultra(self):
        storage=self.root/'Android'
        for package in ('com.sukisu.nova','com.sukisu.ultra'):
            path=storage/'data'/package;path.mkdir(parents=True);(path/'valuable').write_text('keep')
        self.run_adapter('set','hide_ksu_directories','true')
        self.run_adapter('late',ZM75_STORAGE_ROOT=str(storage),TEST_FEATURES='CONFIG_KSU_SUSFS_SUS_PATH')
        self.assertEqual(len(list(storage.rglob('valuable'))),2)
        self.assertIn('com.sukisu.nova',self.calls());self.assertIn('com.sukisu.ultra',self.calls())
    def test_saved_external_flag_blocks_new_rules_and_properties(self):
        (self.root/'external').write_text('ReSuSFS\n')
        self.run_adapter('set','hide_oem_unlocking_toggle','true')
        self.run_adapter('late')
        self.assertNotIn('ro.oem_unlock_supported',self.calls())
        self.run_adapter('set','sus_path_uid_filter','true')
        self.run_adapter('late',ok=False,TEST_FEATURES='CONFIG_KSU_SUSFS_SUS_PATH')
        self.assertNotIn('susfs:set_sus_path_uid_filter',self.calls())
if __name__=='__main__':unittest.main()
