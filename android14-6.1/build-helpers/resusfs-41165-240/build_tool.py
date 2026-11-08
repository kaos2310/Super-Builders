#!/usr/bin/env python3
"""Build the exact vendored official SUSFS CLI for Android ARM64."""
from pathlib import Path
import argparse,hashlib,json,subprocess,struct
HERE=Path(__file__).resolve().parent
def sha(data):return hashlib.sha256(data).hexdigest()
def build(ndk,output):
 source=json.loads((HERE/'SOURCE.json').read_text())
 for name,digest in source['source_files_sha256'].items():
  if sha((HERE/'upstream'/name).read_bytes())!=digest:raise RuntimeError('Official C source drift: '+name)
 platform='windows-x86_64' if (ndk/'toolchains/llvm/prebuilt/windows-x86_64').is_dir() else 'linux-x86_64'
 clang=ndk/f'toolchains/llvm/prebuilt/{platform}/bin/clang'
 if platform.startswith('windows'):clang=clang.with_suffix('.exe')
 files=sorted((HERE/'upstream').glob('*.c'))+sorted((HERE/'upstream/features').glob('*.c'))
 output.parent.mkdir(parents=True,exist_ok=True)
 command=[str(clang),'--target=aarch64-linux-android26','-O3','-fstack-protector-strong','-D_FORTIFY_SOURCE=2','-fPIC','-flto=thin','-ffunction-sections','-fdata-sections','-fvisibility=hidden','-Wl,--gc-sections','-Wl,-z,max-page-size=16384','-I'+str(HERE/'upstream/includes'),*map(str,files),'-o',str(output)]
 subprocess.run(command,check=True)
 binary=output.read_bytes()
 if binary[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',binary,18)[0]!=183:raise RuntimeError('Not an AArch64 ELF')
 proof=dict(source,sha256=sha(binary),bytes=len(binary),target='aarch64-linux-android26',compiler=subprocess.check_output([str(clang),'--version'],text=True).splitlines()[0],source_file_count=len(files),built_from_official_c_sources=True,device_installation_tested=False)
 (output.parent/'SUSFS-TOOL-BUILD.json').write_text(json.dumps(proof,indent=2)+'\n')
 print(json.dumps({k:v for k,v in proof.items() if k!='source_files_sha256'},indent=2));return proof
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ndk',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();build(a.ndk,a.output)
