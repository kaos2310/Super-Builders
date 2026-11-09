"""Package only an explicit source allowlist; never include keys or test data."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist';DIST.mkdir(exist_ok=True)
TOP={'.gitignore','PLAN.md','README.md','VERIFICATION.md','config.json','center_core.py',
     'desktop.py','Start-Web.cmd','package.json','package-lock.json'}
DIRS={'web','android','ci','tools','tests','integration'}

def sha(data):return hashlib.sha256(data).hexdigest()
def sources():
    result={}
    for p in ROOT.iterdir():
        if p.name in TOP and p.is_file():result[p.relative_to(ROOT).as_posix()]=p.read_bytes()
        elif p.name in DIRS and p.is_dir():
            for f in p.rglob('*'):
                if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc':
                    result[f.relative_to(ROOT).as_posix()]=f.read_bytes()
    assert not any('private/' in n or '.test-results/' in n or n.endswith(('.p12','.jks')) for n in result)
    return result

def archive(path,files):
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo(name,(2026,11,9,0,0,0));info.create_system=3;info.external_attr=0o100644<<16;info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,data)
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        assert set(z.namelist())==set(files)

files=sources()
source_zip=DIST/'SukiSU-Build-Center-Source-1.0.0.zip'
archive(source_zip,{'SukiSU-Build-Center/'+n:d for n,d in files.items()})

web={n:d for n,d in files.items() if n.startswith('web/') or n in {'desktop.py','center_core.py','config.json','Start-Web.cmd','README.md','VERIFICATION.md'}}
web['SukiSU-Build-Center.exe']=(DIST/'SukiSU-Build-Center-1.0.0.exe').read_bytes()
archive(DIST/'SukiSU-Build-Center-Web-1.0.0.zip',{'SukiSU-Build-Center-Web/'+n:d for n,d in web.items()})

payload={}
for name,data in files.items():
    if name.startswith('integration/.github/workflows/'):
        payload[name.removeprefix('integration/')]=data
    payload['build-center/'+name]=data
archive(DIST/'SukiSU-Build-Center-GitHub-Integration-1.0.0.zip',payload)
manifest={'schema':1,'repository':'kaos2310/Super-Builders','target_ref':'main',
    'workflow_files':sorted(n for n in payload if n.startswith('.github/workflows/')),
    'file_count':len(payload),'files':{n:sha(d) for n,d in sorted(payload.items())},
    'publication_performed':False,'schedule_activated':False,'new_kernel_build_started':False}
(DIST/'GITHUB-PAYLOAD.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf-8')
shutil.copyfile(ROOT/'.test-results/SuSFS-v2.4.0-69b8e734-samsung.zip',DIST/'SuSFS-v2.4.0-69b8e734-sources.zip')
sums=''.join(sha(p.read_bytes())+'  '+p.name+'\n' for p in sorted(DIST.iterdir()) if p.is_file() and p.name!='SHA256SUMS.txt')
(DIST/'SHA256SUMS.txt').write_text(sums,encoding='utf-8')
print(json.dumps({'payload_files':len(payload),'workflow_files':len(manifest['workflow_files']),
    'packages':[{'name':p.name,'bytes':p.stat().st_size,'sha256':sha(p.read_bytes())} for p in sorted(DIST.iterdir()) if p.is_file()]},indent=2))
