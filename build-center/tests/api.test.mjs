import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Github, selectKernelArtifact, assertRepository, selectReleaseAssets, selectEzj1ManagerAssets, apiError} from '../web/api.js';

const run={id:42,status:'completed',conclusion:'success'};
test('EZJ1 manager feed requires its own release identity and checksum',()=>{
  const a={name:'SukiSU_EZJ1_v4.3.0-r2-runtime1_41168-arm64-v8a-release.apk',digest:'sha256:'+'b'.repeat(64),
    browser_download_url:'https://github.com/kaos2310/Super-Builders/releases/download/build-center-v1.1.0/manager.apk'};
  assert.deepEqual(selectEzj1ManagerAssets([{assets:[a]}]),[a]);
  for(const bad of [{draft:true,assets:[a]},{prerelease:true,assets:[a]},{assets:[{...a,digest:''}]},
    {assets:[{...a,browser_download_url:'https://example.org/manager.apk'}]},
    {assets:[{...a,name:a.name.replace('SukiSU_EZJ1','SukiSU')}]}])assert.deepEqual(selectEzj1ManagerAssets([bad]),[]);
});
const artifact={id:1,name:'6.1.162-SukiSU-41168-S928BXXS6EZJ1-EUX-Strict-AnyKernel3-Flash',digest:'sha256:'+'a'.repeat(64),expired:false,workflow_run:{id:42}};
test('successful strict kernel selected, debug artifact never offered',()=>{
  assert.equal(selectKernelArtifact([{...artifact,name:'debug-AnyKernel3'},artifact],run),artifact);
});
test('partial, failed and expired builds never become downloadable kernels',()=>{
  for(const r of [{...run,status:'in_progress'},{...run,conclusion:'failure'}])assert.equal(selectKernelArtifact([artifact],r),null);
  assert.equal(selectKernelArtifact([{...artifact,expired:true}],run),null);
});
test('artifact must belong to selected run and have digest',()=>{
  assert.equal(selectKernelArtifact([{...artifact,workflow_run:{id:43}}],run),null);
  assert.equal(selectKernelArtifact([{...artifact,digest:null}],run),null);
});
test('EZJ1 client rejects an otherwise valid EZIF kernel',()=>{
  assert.equal(selectKernelArtifact([{...artifact,name:artifact.name.replace('S928BXXS6EZJ1','S928BXXU6EZIF')}],run),null);
});
test('GitHub token is never sent to GitLab',async()=>{
  let actual;const api=new Github(async b=>{actual=b;return {status:200,data:{}};},'private');
  await api.call('https://gitlab.com/api/v4/projects/simonpunk%2Fsusfs4ksu/repository/commits/main');
  assert.equal(actual.token,'');
});
test('dispatch uses correlation id, selected channel and no token in body',async()=>{
  let sent;const api=new Github(async b=>{sent=b;return {status:204,data:null};},'private');
  const id=await api.dispatch('main','release');
  assert.equal(sent.data.inputs.request_id,id);assert.equal(sent.data.inputs.channel,'release');
  assert.equal(sent.data.inputs.force,'false');assert.equal(sent.data.ref,'main');assert.ok(!JSON.stringify(sent.data).includes('private'));
});
test('dispatch without token is rejected before network request',async()=>{
  const api=new Github(()=>{throw new Error('network must not run');});await assert.rejects(()=>api.dispatch('main','main'),/Actions-Schreibrecht/);
});
test('repository validation rejects injected paths',()=>{
  assert.equal(assertRepository('kaos2310/Super-Builders'),'kaos2310/Super-Builders');
  for(const bad of ['a/b/c','https://github.com/a/b','a/b?token=x','../b']){
    assert.throws(()=>assertRepository(bad));
  }
});
test('only releases with immutable build manifest become automation results',()=>{
  const candidate={tag_name:'s928b-ezj1-suki41168-susfs2.4.0-a-b',assets:[{name:'build-plan.json'}]};
  assert.deepEqual(selectReleaseAssets([{...candidate,draft:true},{tag_name:'other',assets:[]},candidate]),[candidate]);
  assert.deepEqual(selectReleaseAssets([{...candidate,tag_name:candidate.tag_name.replace('ezj1','ezif')}]),[]);
});
test('expired artifacts and API rate limits have actionable errors',()=>{
  assert.match(apiError(410),/abgelaufen/);assert.match(apiError(403),/API-Limit/);
});
