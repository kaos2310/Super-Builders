import {test} from 'node:test';
import assert from 'node:assert/strict';
import * as api from '../web/api.js';

const source = {sukisu_commit:'d'.repeat(40),sukisu_code:41179,susfs_commit:'6'.repeat(40)};
const controllerSha = 'a'.repeat(40);
const current = `ARGS+=(--expected-main-commit ${source.sukisu_commit} --expected-main-code 41179)\nARGS+=(--expected-susfs-commit ${source.susfs_commit})`;
const ok = data => ({status:200,headers:{},data});
const file = text => ({encoding:'base64',content:Buffer.from(text).toString('base64')});

test('a latest source label does not certify an unpinned old controller', () => {
  assert.equal(api.workflowMatches('python3 check_updates.py --channel main',source),false);
  assert.equal(api.workflowMatches(current.split('\n').map(line=>'# '+line).join('\n'),source),false);
  assert.equal(api.workflowMatches(current,source),true);
});

test('controller must match both source commits and the version code', () => {
  assert.equal(api.workflowMatches(current.replace('41179','41178'),source),false);
  assert.equal(api.workflowMatches(current.replace(source.susfs_commit,'7'.repeat(40)),source),false);
});

test('Android can find the matching published controller instead of stale main', async () => {
  const github = new api.Github(async body => {
    if(body.url.includes('/commits/codex%2Fbuild-center-auto-updates'))return {status:404,headers:{},data:{}};
    if(body.url.includes('/commits/'))return ok({sha:body.url.endsWith('/main')?'b'.repeat(40):controllerSha});
    if(body.url.includes('/contents/'))return ok(file(body.url.endsWith(controllerSha)?current:'python3 check_updates.py'));
    if(body.url.includes('/runs?'))return ok({workflow_runs:[
      {head_branch:'main',display_title:'Build Center',status:'completed',conclusion:'success'},
      {head_branch:'codex/fixed',display_title:'SukiSU 41179 EZJ1',status:'in_progress'}
    ]});
    throw Error('Unexpected request');
  });
  const selected=await github.compatibleController(source,'main');
  assert.equal(selected.ref,'codex/fixed');
  assert.equal(selected.sha,controllerSha);
});

test('source/controller mismatch is rejected before a build is submitted', async () => {
  let submitted=0;
  const github=new api.Github(async body=>{
    if(body.method==='POST'){submitted++;return {status:204};}
    if(body.url.includes('/commits/'))return ok({sha:controllerSha});
    return ok(file(current.replace(source.sukisu_commit,'e'.repeat(40))));
  },'test-only-not-a-credential');
  await assert.rejects(()=>github.dispatch('main','main',false,{sources:source,controllerSha}),/Quellen|Controller/);
  assert.equal(submitted,0);
});

test('the pipeline list is restricted to the selected workflow branch', async () => {
  let url;
  const github=new api.Github(async body=>{url=body.url;return ok({workflow_runs:[]});});
  await github.runs('codex/fixed');
  assert.equal(new URL(url).searchParams.get('branch'),'codex/fixed');
});

test('a moved controller branch is rechecked even if its source pins stay identical', async () => {
  let submitted=0;
  const github=new api.Github(async body=>{
    if(body.method==='POST'){submitted++;return {status:204};}
    return body.url.includes('/commits/')?ok({sha:'b'.repeat(40)}):ok(file(current));
  },'test-only-not-a-credential');
  await assert.rejects(()=>github.dispatch('codex/fixed','main',false,{sources:source,controllerSha}),/Controller wurde geändert/);
  assert.equal(submitted,0);
});

test('a successful planning-only run is never displayed as a built kernel', () => {
  const run={id:17,status:'completed',conclusion:'success'};
  const result=api.runOutcome(run,[{name:'Kernel und Samsung Strict KMI / CRC',conclusion:'skipped'}],[]);
  assert.equal(result.text,'KEIN KERNEL GEBAUT');
  assert.equal(result.className,'neutral');
  const artifact={name:'S928BXXS6EZJ1-EUX-Strict-AnyKernel3-Flash',digest:'sha256:'+'a'.repeat(64)};
  assert.equal(api.runOutcome(run,[],[artifact]).text,'KERNEL-ZIP BEREIT');
});
