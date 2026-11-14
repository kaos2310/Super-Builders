import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {Github} from '../web/api.js';

const controllerSha = 'a'.repeat(40);
const workflow = "env:\n  BUILD_CENTER_PROTOCOL: '2'\njobs:\n  resolve:\n    steps: []\n";
const resolver = '# resolver with immutable source checks\n';
const sha256 = text => createHash('sha256').update(text).digest('hex');
const manifest = {schema:2,workflow:'build-center.yml',source_binding:'source-request-v1',
  profile:'S928BXXS6EZJ1-EUX-android14-6.1.162',channels:['main','release'],
  workflow_sha256:sha256(workflow),resolver_sha256:sha256(resolver)};
const source = {channel:'main',sukisu_commit:'b'.repeat(40),sukisu_code:41181,
  sukisu_count:3996,susfs_commit:'c'.repeat(40)};
const ok = data => ({status:200,headers:{},data});
const file = text => ok({encoding:'base64',content:Buffer.from(text).toString('base64')});

function fixture({badManifest=false,moved=false,manifestChange={},resolverChange=false}={}) {
  const posts=[];
  const github = new Github(async body => {
    if(body.method==='POST'){posts.push(body.data);return {status:204};}
    if(body.url.includes('/commits/'))return ok({sha:moved?'d'.repeat(40):controllerSha});
    if(body.url.includes('/contents/.github/'))return file(workflow);
    if(body.url.includes('/contents/build-center/controller.json'))return file(JSON.stringify({...manifest,...manifestChange,...(badManifest?{workflow_sha256:'0'.repeat(64)}:{})}));
    if(body.url.includes('/contents/build-center/ci/check_updates.py'))return file(resolverChange?'changed resolver':resolver);
    if(body.url.includes('/runs?'))return ok({workflow_runs:[]});
    throw Error('Unexpected request: '+body.url);
  },'test-only-not-a-credential');
  return {github,posts};
}

test('the same automatic controller accepts successive SukiSU and SuSFS updates', async () => {
  const {github}=fixture();
  for(const sources of [source,{...source,sukisu_commit:'d'.repeat(40),sukisu_code:41182,
    sukisu_count:3997,susfs_commit:'e'.repeat(40)}]) {
    const controller=await github.compatibleController(sources,'main');
    assert.equal(controller.protocol,2);
    assert.equal(controller.sha,controllerSha);
  }
});

test('automatic dispatch binds the displayed pair, count, channel and controller without repository writes', async () => {
  const {github,posts}=fixture();
  await github.dispatch('main','main',false,{sources:source,controllerSha});
  assert.equal(posts.length,1);
  assert.deepEqual(JSON.parse(posts[0].inputs.source_request),{schema:1,channel:'main',
    sukisu_commit:source.sukisu_commit,sukisu_code:41181,sukisu_count:3996,
    susfs_commit:source.susfs_commit,controller_sha:controllerSha});
  assert.equal(posts[0].inputs.force,'false');
});

test('the release channel uses the same source binding', async () => {
  const {github,posts}=fixture();
  await github.dispatch('main','release',false,{sources:{...source,channel:'release'},controllerSha});
  assert.equal(JSON.parse(posts[0].inputs.source_request).channel,'release');
});

test('a manifest cannot certify another workflow or a different firmware profile', async () => {
  for(const options of [{badManifest:true},{resolverChange:true},{manifestChange:{profile:'S928BXXU6EZIF'}},
    {manifestChange:{channels:['pinned']}},{manifestChange:{source_binding:'unchecked-latest'}}]) {
    const {github,posts}=fixture(options);
    await assert.rejects(()=>github.dispatch('main','main',false,{sources:source,controllerSha}),/Controller|Manifest/);
    assert.equal(posts.length,0);
  }
});

test('an incomplete app review cannot dispatch the automatic controller', async () => {
  const {github,posts}=fixture();
  await assert.rejects(()=>github.dispatch('main','main',false,{sources:source}),/Quellen|Versions/);
  assert.equal(posts.length,0);
});

test('a removed legacy branch migrates without relying on an existing Actions run', async () => {
  const {github}=fixture();
  const transport=github.transport;
  github.transport=async body=>body.url.includes('/commits/codex%2Fsukisu-41179-guard6-ezj1')
    ? {status:404,headers:{},data:{}} : transport(body);
  const selected=await github.compatibleController(source,'codex/sukisu-41179-guard6-ezj1');
  assert.equal(selected.ref,'codex/build-center-auto-updates');
  assert.equal(selected.protocol,2);
});

test('automatic dispatch still rejects a changed controller before POST', async () => {
  const {github,posts}=fixture({moved:true});
  await assert.rejects(()=>github.dispatch('main','main',false,{sources:source,controllerSha}),/Controller wurde geändert/);
  assert.equal(posts.length,0);
});

test('automatic dispatch rejects inconsistent counts and channels before POST', async () => {
  for(const sources of [{...source,sukisu_count:3995},{...source,channel:'release'}]) {
    const {github,posts}=fixture();
    await assert.rejects(()=>github.dispatch('main','main',false,{sources,controllerSha}),/Quellen|Versions|Kanal/);
    assert.equal(posts.length,0);
  }
});
