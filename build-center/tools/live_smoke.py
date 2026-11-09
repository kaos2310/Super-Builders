"""Read-only live APIs, real cached kernel, and the exact current source migration."""
from pathlib import Path
import importlib.util
import io
import json
import subprocess
import sys
import tarfile

ROOT=Path(__file__).resolve().parents[1];WS=ROOT.parent;sys.path.insert(0,str(ROOT))
from center_core import checked_file,request,resolve_sources
from ci.bootstrap import prepare

out=ROOT/'.test-results';out.mkdir(exist_ok=True)
plan=resolve_sources()
config=json.loads((ROOT/'config.json').read_text())
for key in ('baseline_commit','susfs_release_base','susfs_functional_base'):plan[key]=config[key]
(out/'live-plan.json').write_text(json.dumps(plan,indent=2)+'\n',encoding='utf-8')
result={'live_sukisu':plan['sukisu_code'],'live_sukisu_pin':plan['sukisu_commit'],
        'live_susfs':plan['susfs_version'],'live_susfs_pin':plan['susfs_commit'],
        'full_kernel_build_executed':False,'repository_modified':False}
reference=WS/'work/sukisu-41165-20261108/kernel-final-artifact.zip'
if reference.exists():
    raw,name,digest=checked_file(reference.read_bytes(),'cached-reference.zip',
        'e2c19e21476883513175df698dbaac68818b3514e4b68f6a5f924683c9c5cb11','kernel-artifact')
    assert digest=='94e25345a527af5e03173be78ebb751f9a44180f84b2c518dac3850e4084b548'
    result['real_cached_kernel_unwrapped_and_verified']={'filename':name,'sha256':digest,'bytes':len(raw)}
candidate=out/'candidate'
if candidate.exists():raise RuntimeError('Fresh live-smoke workspace required; existing test files were preserved')
candidate.mkdir()
archive=subprocess.check_output(['git','-C',str(WS/'Super-Builders-41165'),'archive',config['baseline_commit'],
    'android14-6.1/build-helpers','.github/workflows'])
with tarfile.open(fileobj=io.BytesIO(archive)) as tar:tar.extractall(candidate,filter='data')
prepare(candidate,plan)
runtime=candidate/'android14-6.1/build-helpers/_center_runtime.py'
spec=importlib.util.spec_from_file_location('live_ci_runtime',runtime);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
# This is a real upstream comparison; the current new SuSFS commit only touches
# the KernelSU-specific patch, not the SukiSU/GKI files. No stock kernel is needed.
m.prepare_susfs(candidate/'common-not-needed-for-unchanged-gki-patch')
delta=json.loads((candidate/'.build-center-susfs/upstream-changes.json').read_text())
result['real_susfs_delta']=delta
new_helper=candidate/f"android14-6.1/build-helpers/configure-sukisu-{plan['sukisu_code']}.py"
assert plan['sukisu_commit'] in new_helper.read_text()
evidence=json.loads((candidate/f"android14-6.1/build-helpers/sukisu-{plan['sukisu_code']}-susfs/PREFLIGHT.json").read_text())
assert evidence['full_kernel_link_tested'] is False and evidence['historical_evidence_reused'] is False
result['real_candidate_prepared_without_inherited_compilation_evidence']=True
(out/'live-smoke-results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,indent=2))
