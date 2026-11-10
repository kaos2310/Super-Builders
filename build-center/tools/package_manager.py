"""Publish exact upstream source, the bounded adaptation, and verified native inputs."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import io
import json
import subprocess
import tarfile
import zipfile

PIN = '674aa00c18adc3d7ef4069c03018d6194230865a'
KPM = '1c5b608916357ac86a94cc736e235db1fac4a29d'
def sha(data): return hashlib.sha256(data).hexdigest()
def git(source, *args): return subprocess.check_output(['git', '-C', str(source), *args])

def main():
    p=argparse.ArgumentParser()
    for name in ('source','kernelpatch','native','proof','output'): p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    assert git(a.source,'rev-parse','HEAD').decode().strip()==PIN
    assert git(a.kernelpatch,'rev-parse','HEAD').decode().strip()==KPM
    proof=json.loads(a.proof.read_text())
    assert proof['sukisu_pin']==PIN and proof['kernelpatch_pin']==KPM and proof['native_binaries_byte_exact']
    root=Path(__file__).resolve().parents[1]
    adaptation=root/'manager';adaptation.mkdir(exist_ok=True)
    patch=git(a.source,'diff','--binary','HEAD','--','manager')
    (adaptation/'upstream.patch').write_bytes(patch)
    changed=git(a.source,'diff','--name-only','HEAD','--','manager').decode().splitlines()
    # A Git patch reconstructs canonical LF text. Hash and publish those same
    # bytes so Windows checkouts and patch-based rebuilds share one identity.
    adapted={name:(a.source/name).read_bytes().replace(b'\r\n',b'\n') for name in changed}
    manifest=dict(proof,patch_sha256=sha(patch),changed_source_sha256={name:sha(data) for name,data in adapted.items()})
    (adaptation/'BUILD-IDENTITY.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
    files={}
    for source, prefix in [(a.source,'SukiSU'),(a.kernelpatch,'KernelPatch')]:
        archive=git(source,'archive','HEAD')
        with tarfile.open(fileobj=io.BytesIO(archive)) as source_tar:
            for entry in source_tar.getmembers():
                if entry.isfile():
                    name=PurePosixPath(entry.name)
                    assert not name.is_absolute() and '..' not in name.parts
                    files[prefix+'/'+entry.name]=source_tar.extractfile(entry).read()
    for name,data in adapted.items(): files['SukiSU/'+name]=data
    for name in ('ksud','kptools-android','kpimg','MANAGER-NATIVE-INPUTS.json'):
        files['native-inputs/'+name]=(a.native/name).read_bytes()
    files['SukiSU/manager/app/src/main/jniLibs/arm64-v8a/libksud.so']=files['native-inputs/ksud']
    for name in ('README.md','BUILD-IDENTITY.json','upstream.patch','build.ps1'):
        files[name]=(adaptation/name).read_bytes()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(a.output,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(files.items()): z.writestr('SukiSU-EZJ1-Source/'+name,data)
    with zipfile.ZipFile(a.output) as z: assert z.testzip() is None
    print(json.dumps({'source_files':len(files),'package':a.output.name,'sha256':sha(a.output.read_bytes()),'bytes':a.output.stat().st_size}))

if __name__=='__main__':main()
