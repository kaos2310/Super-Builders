"""Read only Samsung state through an explicitly selected ADB serial."""
from pathlib import Path
import argparse
import json
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--serial',required=True);p.add_argument('--adb',default='D:/StudioAndroid/platform-tools/adb.exe');a=p.parse_args()
    def shell(command):
        try:
            r=subprocess.run([a.adb,'-s',a.serial,'shell',command],capture_output=True,text=True,timeout=25,encoding='utf-8',errors='replace')
            return {'exit_code':r.returncode,'output':(r.stdout+r.stderr).strip()}
        except subprocess.TimeoutExpired:return {'exit_code':124,'output':'ADB-Abfrage hat das Zeitlimit erreicht.'}
    result={}
    for key,command in {
        'model':'getprop ro.product.model','firmware':'getprop ro.build.PDA','csc':'getprop ro.csc.sales_code',
        'android':'getprop ro.build.version.release','sdk':'getprop ro.build.version.sdk',
        'kernel':'uname -a','selinux':'getenforce','build_center':'pm path com.kaoslab.buildcenter',
        'root':'su -c id',
        'ksud_version':'su -c "/data/adb/ksu/bin/ksud -V"',
        'susfs_private_version':'su -c "/data/adb/modules/ReSuSFS/bin/ksu_susfs show version"',
        'susfs_global_version':'su -c "/data/adb/ksu/bin/ksu_susfs show version"',
        'susfs_enabled_features':'su -c "/data/adb/modules/ReSuSFS/bin/ksu_susfs show enabled_features"',
        'resusfs_module':'su -c "cat /data/adb/modules/ReSuSFS/module.prop"',
    }.items():result[key]=shell(command)
    package=shell('dumpsys package com.sukisu.ultra')
    result['sukisu_manager']={'exit_code':package['exit_code'],'version_lines':re.findall(r'^\s*(?:versionCode=\S+[^\n]*|versionName=[^\n]*)',package['output'],re.M)}
    out=ROOT/'.test-results/adb-samsung.json';out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True,indent=2))

if __name__=='__main__':main()
