import {test} from 'node:test';
import assert from 'node:assert/strict';
import {AutomaticBuilder} from '../web/automation.js';
import {releaseMatchesSources} from '../web/api.js';

const source={channel:'main',sukisu_commit:'a'.repeat(40),susfs_commit:'b'.repeat(40),sukisu_count:4008,
  sukisu_code:35004,sukisu_version_formula:{base:30000,offset:996,operation:'+'},
  release_tag:'s928b-ezjb-suki35004-susfs2.4.0-aaaaaaaa-bbbbbbbb'};
const controller={ref:'codex/build-center-ezjb-auto-20261122',sha:'c'.repeat(40),protocol:2,automatic:true};
function fixture() {
  const data=new Map(),storage={getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)},posts=[];
  const api={token:'test-only',repo:'kaos2310/Super-Builders',runs:async()=>[],currentRelease:async()=>null,
    recentFailure:async()=>null,dispatch:async(ref,channel,force,expected)=>{posts.push({ref,channel,force,expected});return expected.requestId;}};
  return {storage,posts,api,builder:new AutomaticBuilder(storage)};
}
test('new upstream versions build without opening the manual confirmation dialog',async()=>{
  const {api,builder,posts}=fixture();const result=await builder.ensure(api,source,controller);
  assert.equal(result.outcome,'submitted');assert.equal(posts.length,1);
  assert.equal(posts[0].expected.sources.sukisu_code,35004);assert.equal(posts[0].force,false);
});
test('refresh, reload and simultaneous checks cannot submit the same pair twice',async()=>{
  const {api,builder,storage,posts}=fixture();
  await Promise.all([builder.ensure(api,source,controller),builder.ensure(api,source,controller)]);
  await new AutomaticBuilder(storage).ensure(api,source,controller);
  assert.equal(posts.length,1);
});
test('a later source pair uses the same automatic controller',async()=>{
  const {api,builder,posts}=fixture();await builder.ensure(api,source,controller);
  await builder.ensure(api,{...source,sukisu_commit:'d'.repeat(40),sukisu_count:4009,sukisu_code:35005},controller);
  assert.equal(posts.length,2);
});
test('active builds, exact published pairs and failed current controller are not rebuilt',async()=>{
  for(const replacement of [{runs:async()=>[{id:8,status:'in_progress',head_branch:controller.ref}]},
    {currentRelease:async()=>({id:9})},{recentFailure:async()=>({id:10})}]){
    const {api,builder,posts}=fixture();Object.assign(api,replacement);
    await builder.ensure(api,source,controller);assert.equal(posts.length,0);
  }
});
test('changed settings and missing credentials prevent automatic writes',async()=>{
  const {api,builder,posts}=fixture();await builder.ensure(api,source,controller,()=>false);
  api.token='';await builder.ensure(api,source,controller);assert.equal(posts.length,0);
});
test('an unconfirmed POST is not repeated after app restart',async()=>{
  const {api,builder,storage,posts}=fixture();api.dispatch=async()=>{posts.push('attempt');throw Error('connection lost');};
  await assert.rejects(()=>builder.ensure(api,source,controller));
  assert.equal((await new AutomaticBuilder(storage).ensure(api,source,controller)).outcome,'attempted');
  assert.equal(posts.length,1);
});
test('a matching release needs both full source IDs and a checked kernel asset',()=>{
  const release={tag_name:source.release_tag+'-hidden-name-readdir-v2-r42',
    body:'SukiSU commit: '+source.sukisu_commit+'\nSuSFS commit: '+source.susfs_commit,
    assets:[{name:'build-plan.json'},{name:'S928BXXU6EZJB-EUX-AnyKernel3.zip',digest:'sha256:'+'e'.repeat(64)}]};
  assert.equal(releaseMatchesSources(release,source),true);
  assert.equal(releaseMatchesSources({...release,body:release.body.replace(source.susfs_commit,'f'.repeat(40))},source),false);
  assert.equal(releaseMatchesSources({...release,assets:[{name:'build-plan.json'}]},source),false);
});
