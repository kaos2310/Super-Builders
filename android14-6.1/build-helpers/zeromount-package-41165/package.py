#!/usr/bin/env python3
"""Reproducible module package retaining the user's complete 41159 feature set."""
from pathlib import Path,PurePosixPath
import argparse,hashlib,json,struct,subprocess,sys,tempfile,zipfile
HERE=Path(__file__).resolve().parent
HELPERS=HERE.parent
PIN='d7d042816b82b200c25b3a93dcc158ba0307cabf'
def sha(data):return hashlib.sha256(data).hexdigest()

def package(helper,output):
    source=HERE/'module-base.zip';base=json.loads((HERE/'BASE.json').read_text())
    if sha(source.read_bytes())!=base['sha256']:raise RuntimeError('Module baseline archive drift')
    data=helper.read_bytes()
    if data[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',data,18)[0]!=183:raise RuntimeError('Runtime helper must be real AArch64 ELF')
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as directory:
        root=Path(directory)
        with zipfile.ZipFile(source) as z:
            for item in z.infolist():
                relative=PurePosixPath(item.filename)
                if relative.is_absolute() or '..' in relative.parts or '\\' in item.filename:raise RuntimeError('Unsafe baseline path')
                raw=z.read(item)
                if sha(raw)!=base['files_sha256'][item.filename]:raise RuntimeError('Baseline member drift')
                target=root/item.filename;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        core=root/'bin/arm64-v8a/zm-native-core'
        core_before=sha(core.read_bytes())
        patched=root/'native240';receipt=root/'NATIVE-SUSFS240.json'
        subprocess.run([sys.executable,'-B',str(HELPERS/'zeromount-susfs240/apply.py'),str(core),str(patched),'--receipt',str(receipt)],check=True)
        core.write_bytes(patched.read_bytes());patched.unlink()
        core_after=sha(core.read_bytes())
        (root/'NATIVE-VERSION-GATE-TESTS.json').write_bytes((HELPERS/'zeromount-susfs240/VERIFICATION.json').read_bytes())
        wrapper=root/'bin/zm';text=wrapper.read_text(encoding='utf-8')
        if text.count(core_before)!=1:raise RuntimeError('Unknown immutable core check')
        wrapper.write_bytes(text.replace(core_before,core_after).encode())
        adapter=root/'bin/zm-brene75';text=adapter.read_text(encoding='utf-8')
        if text.count('[ "$version" = v2.3.0 ] || return 65')!=2:raise RuntimeError('Unknown BRENE ABI guards')
        adapter.write_bytes(text.replace('[ "$version" = v2.3.0 ] || return 65','[ "$version" = v2.4.0 ] || return 65').encode())
        (root/'bin/susfs-runtime').write_bytes(data)
        (root/'customize.sh').write_bytes((HERE/'customize.sh').read_bytes())
        update_binary=root/'META-INF/com/google/android/update-binary'
        update_binary.write_bytes(update_binary.read_bytes().replace(b'ReSukiSU/KernelSU or APatch manager',b'SukiSU manager'))
        (root/'module.prop').write_bytes(('id=meta-zeromount\nname=ZeroMount\nversion=v2.0.216-dev.guard6.13.brene75.susfs240.sukisu41165.ui2\nversionCode=2026110801\nauthor=Enginex0, KAOSLAB integration\ndescription=Guard6.13 + BRENE75 + SUSFS2.4.0 + Runtime v1; integrierte Settings; SukiSU41165 / S928B EZIF.\nmetamodule=1\nbanner=banner.png\n').encode())
        subprocess.run([sys.executable,'-B',str(HELPERS/'zeromount-ui-41165/apply.py'),str(root),'--receipt',str(root/'UI-VERIFICATION.json')],check=True)
        (root/'README-SukiSU41165.md').write_bytes((HERE/'README.md').read_bytes())
        manifest={'schema':5,'sukisu_version':41165,'sukisu_pin':PIN,'susfs_version':'v2.4.0','susfs_release_pin':'a2165b6f875b73e2f87d3c6f12814efac8de061d','baseline':base['sha256'],'native_core_before_sha256':core_before,'native_core_sha256':core_after,'native_update':'exact hash-bound release compatibility patch; no source rebuild claimed','runtime_helper_sha256':sha(data),'configuration_preserved':True,'new_masters_default_enabled':False,'device_module_installation_tested':False}
        (root/'build-manifest.json').write_bytes((json.dumps(manifest,indent=2)+'\n').encode())
        # KernelSU removes installer files; runtime cache and module description change.
        mutable={'module.prop','customize.sh','webroot/cache.json','webroot/zm-init.js','SHA256SUMS','COMPAT-SHA256SUMS'}
        members={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
        for name in ('SHA256SUMS','COMPAT-SHA256SUMS'):
            selected={n:d for n,d in members.items() if n not in {'SHA256SUMS','COMPAT-SHA256SUMS'} and (name=='SHA256SUMS' or n not in mutable)}
            members[name]=''.join(sha(d)+'  '+n+'\n' for n,d in sorted(selected.items())).encode()
        target=output/'ZeroMount-Guard6.13-BRENE75-SUSFS2.4.0-SukiSU41165-arm64.zip'
        with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
            for name,raw in sorted(members.items()):
                info=zipfile.ZipInfo(name,(2026,11,8,0,0,0));info.create_system=3
                executable=name.startswith('bin/') or name.endswith('.sh') or name.endswith('update-binary')
                info.external_attr=(0o100755 if executable else 0o100644)<<16;info.compress_type=zipfile.ZIP_DEFLATED;z.writestr(info,raw)
        with zipfile.ZipFile(target) as z:
            if z.testzip() is not None:raise RuntimeError('Package CRC failed')
            for line in z.read('SHA256SUMS').decode().splitlines():
                digest,name=line.split('  ',1)
                if sha(z.read(name))!=digest:raise RuntimeError('Package digest failed: '+name)
        result=dict(manifest,zip_sha256=sha(target.read_bytes()),zip_name=target.name,bytes=target.stat().st_size,archive_crc_passed=True,all_member_checksums_passed=True)
        (output/'PACKAGE-VERIFICATION.json').write_bytes((json.dumps(result,indent=2)+'\n').encode())
        (output/'SHA256SUMS').write_bytes((result['zip_sha256']+'  '+target.name+'\n').encode())
        print(json.dumps(result,indent=2));return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--runtime-helper',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();package(a.runtime_helper,a.output)
