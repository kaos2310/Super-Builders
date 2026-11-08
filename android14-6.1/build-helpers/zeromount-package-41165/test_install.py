"""Exercise upgrade storage behavior through the actual installer shell script."""
from pathlib import Path
import os,subprocess,tempfile,unittest
HERE=Path(__file__).resolve().parent

class InstallerTests(unittest.TestCase):
    def run_install(self,version='v2.4.0',existing=True):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        state=root/'data/adb/zeromount';state.mkdir(parents=True)
        staged=root/'staged';(staged/'bin/arm64-v8a').mkdir(parents=True)
        tools=root/'tools';tools.mkdir()
        for name,script in {
            'uname':'echo aarch64', 'unzip':':',
        }.items():
            path=tools/name;path.write_text('#!/bin/sh\n'+script+'\n');path.chmod(0o755)
        ksud=root/'ksud';ksud.write_text('#!/bin/sh\necho '+version+'\n');ksud.chmod(0o755)
        (staged/'bin/zm').write_text('#!/bin/sh\nexit 0\n');(staged/'bin/zm').chmod(0o755)
        (staged/'bin/arm64-v8a/zm-native-core').write_text('#!/bin/sh\nexit 0\n');(staged/'bin/arm64-v8a/zm-native-core').chmod(0o755)
        original={
            'config.toml':'[susfs]\nenabled = false\n',
            'switches/susfs.enabled':'false\n','switches/brene.enabled':'true\n',
            'susfs-owner':'ReSuSFS\n','brene71/options':'spoof_hosts=true\n',
            'susfs-rules/custom.json':'{"preserve":true}\n',
        }
        if existing:
            for name,data in original.items():
                path=state/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(data)
        text=(HERE/'customize.sh').read_text().replace('KSUD=/data/adb/ksud','KSUD='+str(ksud)).replace('STATE=/data/adb/zeromount','STATE='+str(state))
        prefix='''abort() { echo "$1" >&2; exit 72; }
set_perm_recursive() { :; }
set_perm() { :; }
ui_print() { :; }
'''
        script=root/'install.sh';script.write_text(prefix+text)
        env=dict(os.environ,PATH=str(tools)+':'+os.environ['PATH'],KSU='true',KSU_SUKISU='true',ZIPFILE='unused',MODPATH=str(staged))
        result=subprocess.run(['bash',str(script)],env=env,capture_output=True,text=True)
        return result,state,original

    def test_upgrade_preserves_all_existing_user_state(self):
        result,state,original=self.run_install();self.assertEqual(result.returncode,0,result.stderr)
        for name,data in original.items():self.assertEqual((state/name).read_text(),data)

    def test_wrong_kernel_rejected_before_state_changes(self):
        result,state,original=self.run_install('v2.3.0');self.assertEqual(result.returncode,72)
        for name,data in original.items():self.assertEqual((state/name).read_text(),data)

    def test_fresh_masters_start_disabled(self):
        result,state,_=self.run_install(existing=False);self.assertEqual(result.returncode,0,result.stderr)
        for name in ('susfs','brene'):self.assertEqual((state/f'switches/{name}.enabled').read_text(),'false\n')

if __name__=='__main__':unittest.main()
