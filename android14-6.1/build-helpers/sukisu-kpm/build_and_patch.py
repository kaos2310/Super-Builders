#!/usr/bin/env python3
"""Build a pinned native KPM engine and audit its transformation of an ARM64 Image."""
from pathlib import Path
import argparse,hashlib,json,os,re,secrets,shutil,subprocess,tarfile,urllib.request
ENGINE_PIN='1c5b608916357ac86a94cc736e235db1fac4a29d'
SUKISU_PIN='ad73573dd9ee66da86b2741e18d7e591999ade24'
GNU_NAME='arm-gnu-toolchain-12.2.rel1-x86_64-aarch64-none-elf'
GNU_SHA='62d66e0ad7bd7f2a183d236ee301a5c73c737c886c7944aa4f39415aab528daf'
HERE=Path(__file__).resolve().parent
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def git(p,*args):return subprocess.check_output(['git','-C',str(p),*args],text=True).strip()
def run(argv,log,env=None,input=None):
    p=subprocess.run(list(map(str,argv)),capture_output=True,text=True,env=env,input=input,timeout=600)
    text=p.stdout+p.stderr
    if input:text=text.replace(input.strip(),'[REDACTED_SECRET]')
    log.write_text(text,encoding='utf-8',newline='\n')
    if p.returncode:raise RuntimeError(str(log)+': command failed, exit '+str(p.returncode))
    return text
def audit_restore(original,restored,start,size):
    if len(original)!=len(restored):raise RuntimeError('Kernel size changed after native unpatch')
    normalized=bytearray(restored);changes=[]
    pac={0xd503233f,0xd503237f,0xd50323bf,0xd50323ff}
    for off in range(0,len(original),4):
        old=original[off:off+4];new=restored[off:off+4]
        if old==new:continue
        if len(old)!=4 or not start<=off<start+size or int.from_bytes(old,'little') not in pac or new!=(0xd503201f).to_bytes(4,'little'):
            raise RuntimeError('Unexpected native patch transformation at '+hex(off))
        changes.append({'offset':off,'before':old.hex(),'after':new.hex()});normalized[off:off+4]=old
    if bytes(normalized)!=original:raise RuntimeError('Normalized recovery differs from original')
    return changes
def build(engine,ksu,work,out):
    if git(ksu,'rev-parse','HEAD')!=SUKISU_PIN:raise RuntimeError('Wrong SukiSU source')
    if git(engine,'rev-parse','HEAD')!=ENGINE_PIN or git(engine,'diff','--name-only','HEAD'):raise RuntimeError('Wrong or modified engine source')
    archive=work/(GNU_NAME+'.tar.xz')
    if not archive.exists():urllib.request.urlretrieve('https://armkeil.blob.core.windows.net/developer/Files/downloads/gnu/12.2.rel1/binrel/'+archive.name,archive)
    if sha(archive)!=GNU_SHA:raise RuntimeError('GNU compiler archive hash mismatch')
    if not (work/GNU_NAME).exists():
        with tarfile.open(archive) as tar:tar.extractall(work,filter='data')
    env=dict(os.environ,SOURCE_DATE_EPOCH=git(engine,'show','-s','--format=%ct','HEAD'))
    run(['make','-C',engine/'kernel','-j4','TARGET_COMPILE='+str(work/GNU_NAME/'bin/aarch64-none-elf-')],out/'engine-build.log',env)
    run(['make','-C',engine/'tools','-j4','CC=gcc'],out/'tool-build.log',env)
    run(['python3','-B',HERE/'test_bridge.py','--engine',engine,'--ksu',ksu,'--receipt',out/'KPM-ABI-TESTS.json'],out/'abi-tests.log')
    for name,src in [('kpimg',engine/'kernel/kpimg'),('kpimg.elf',engine/'kernel/kpimg.elf'),('kptools',engine/'tools/kptools')]:shutil.copyfile(src,out/name)
    (out/'kptools').chmod(0o755)
    elf=(out/'kpimg.elf').read_bytes()
    if elf[:4]!=b'\x7fELF' or int.from_bytes(elf[18:20],'little')!=183:raise RuntimeError('Engine is not AArch64')
    run([out/'kptools','-l','-k',out/'kpimg'],out/'engine-info.log')
    result={'sukisu_pin':SUKISU_PIN,'kernelpatch_pin':ENGINE_PIN,'gnu_archive_sha256':GNU_SHA,
            'files':{n:sha(out/n) for n in ('kpimg','kpimg.elf','kptools')},'device_tested':False}
    (out/'ENGINE-BUILD.json').write_text(json.dumps(result,indent=2)+'\n')
    return result
def patch(image,tool,kpimg,out,build_receipt):
    original=image.read_bytes()
    if original[56:60]!=b'ARM\x64':raise RuntimeError('Uncompressed ARM64 Image required')
    # Original is retained outside AnyKernel so it cannot be selected by a flasher.
    backup=out/'Original.Image';shutil.copyfile(image,backup)
    target=out/'Patched.Image';restored=out/'Recovered.Image'
    key=secrets.token_hex(24)
    log=run([tool,'-p','--skey-fd','0','-i',backup,'-k',kpimg,'-o',target],out/'patch.log',input=key+'\n')
    run([tool,'-u','-i',target,'-o',restored],out/'recovery.log')
    matches=re.findall(r'Synced NOP modifications .*\(offset: (0x[0-9a-f]+), size: (0x[0-9a-f]+)\)',log)
    if len(matches)!=1:raise RuntimeError('Expected one native PAC transformation range')
    start,size=map(lambda s:int(s,16),matches[0])
    if size!=0x2000 or not 0<=start<start+size<=len(original):raise RuntimeError('Unexpected native patch range')
    changes=audit_restore(original,restored.read_bytes(),start,size)
    patched=target.read_bytes()
    if patched==original or patched[56:60]!=b'ARM\x64' or len(patched)<=len(original):raise RuntimeError('No valid engine added')
    config_start=original.find(b'IKCFG_ST')
    config_end=original.find(b'IKCFG_ED',config_start+8)
    if config_start<0 or config_end<config_start or original[config_start:config_end+8] not in patched:raise RuntimeError('Embedded configuration changed')
    run([tool,'-l','-i',target],out/'patched-info.log')
    receipt={'engine':build_receipt,'original_sha256':sha(backup),'patched_sha256':sha(target),
             'recovered_sha256':sha(restored),'normalized_recovery_matches_original':True,
             'native_pac_nop_changes':changes,'native_unpatch_is_byte_exact':not changes,
             'source_kmi_and_crc_gates_required':True,'device_tested':False}
    (out/'KPM-IMAGE.json').write_text(json.dumps(receipt,indent=2)+'\n')
    # Publish only after all static checks; retain the exact original for rollback.
    shutil.copyfile(target,image)
    return receipt
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ksu',type=Path,required=True);p.add_argument('--work-dir',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--image',type=Path);p.add_argument('--engine',type=Path);a=p.parse_args()
    work=a.work_dir.resolve();out=a.output.resolve();work.mkdir(parents=True,exist_ok=True);out.mkdir(parents=True,exist_ok=True)
    engine=a.engine or work/'KernelPatch'
    if not engine.exists():
        subprocess.run(['git','clone','-q','https://github.com/SukiSU-Ultra/SukiSU_KernelPatch_patch.git',str(engine)],check=True)
        subprocess.run(['git','-C',str(engine),'checkout','-q','--detach',ENGINE_PIN],check=True)
    result=build(engine.resolve(),a.ksu.resolve(),work,out)
    if a.image:result=patch(a.image.resolve(),out/'kptools',out/'kpimg',out,result)
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
