import assert from 'node:assert/strict';
import {FEATURES, READ_COMMANDS, runtimeState, runtimeCommand, mayWrite, startHub, bridge} from './zm-susfs-hub.mjs';
import {applyAppearance} from './zm-susfs-theme.mjs';
import {createSusfsEntry} from './zm-susfs-menu.mjs';

const enabled = {schema:2,susfs_enabled:true,brene_enabled:true,susfs_effective:true,brene_effective:true,external_owner_active:false};
const state = {protocol:'kaoslab-susfs-runtime',version:1,size:48,supported:15,enabled:15,generation:41};
let assertions = 0;
function check(fn) { fn(); assertions++; }
check(()=>assert.equal(runtimeState(state), state));
for (const field of ['protocol','version','size','supported','enabled','generation']) {
  const value = {...state,[field]: field==='protocol'?'other':-1};
  check(()=>assert.throws(()=>runtimeState(value)));
}
for (const generation of [0, 0x100000000, NaN, 1.5]) check(()=>assert.throws(()=>runtimeState({...state,generation})));
check(()=>assert.throws(()=>runtimeState({...state,supported:3,enabled:15})));
for (const feature of FEATURES) {
  check(()=>assert.match(runtimeCommand(feature.key,false,state,enabled),new RegExp(`allowed susfs && .*allowed brene && .*set ${feature.key} 0 41$`)));
  check(()=>assert.throws(()=>runtimeCommand(feature.key,true,{...state,supported:0,enabled:0},enabled)));
}
for (const flag of ['susfs_enabled','brene_enabled','susfs_effective','brene_effective']) {
  const owner = {...enabled,[flag]:false};
  check(()=>assert.equal(mayWrite(owner),false));
  check(()=>assert.throws(()=>runtimeCommand('uid-gating',false,state,owner)));
}
check(()=>assert.throws(()=>runtimeCommand('uid-gating; reboot',true,state,enabled)));
check(()=>assert.throws(()=>runtimeCommand('uid-gating','true',state,enabled)));
check(()=>assert.throws(()=>runtimeCommand('uid-gating',true,state,{...enabled,external_owner_active:true})));

class Element {
  constructor() { this.children=[]; this.handlers={}; this.disabled=false; this.textContent=''; this.checked=false; }
  append(...children) {this.children.push(...children);}
  addEventListener(name,handler) {this.handlers[name]=handler;}
}
function documentFixture() {
  const ids = new Map(['refresh','message','susfs-state','brene-state','owner-state','runtime-state','runtime-settings','kernel-state','policy-state'].map(id=>[id,new Element()]));
  return {getElementById:id=>ids.get(id),createElement:()=>new Element(),ids};
}
function inputFor(doc, key) {return doc.ids.get('runtime-settings').children[FEATURES.findIndex(item=>item.key===key)].children[0];}

// Opening the hub only issues status reads, even with an external owner.
for (const external of [true,false]) {
  const doc = documentFixture(), commands=[];
  const owner = {...enabled,external_owner_active:external,susfs_effective:!external,brene_effective:!external};
  const run = async command => {commands.push(command); return JSON.stringify(command===READ_COMMANDS.owners?owner:command===READ_COMMANDS.runtime?state:{susfs:{kernel_reported_version:'v2.4.0',features:['CONFIG_KSU_SUSFS']}});};
  await startHub(doc,{confirm:()=>true},run);
  check(()=>assert.deepEqual(commands,Object.values(READ_COMMANDS)));
  check(()=>assert.equal(inputFor(doc,'uid-gating').disabled,external));
  check(()=>assert.match(doc.ids.get('kernel-state').textContent,/v2.4.0/));
}

// A missing/old runtime ABI disables all setters and preserves native diagnostics.
{
  const doc = documentFixture(),commands=[];
  await startHub(doc,{},async command=>{commands.push(command); if(command===READ_COMMANDS.runtime) throw Error('ABI unavailable'); return JSON.stringify(command===READ_COMMANDS.owners?enabled:{susfs:{features:[]}});});
  check(()=>assert.equal(inputFor(doc,'uid-gating').disabled,true));
  check(()=>assert.match(doc.ids.get('runtime-state').textContent,/nicht verfügbar/));
  check(()=>assert(commands.every(command=>!command.includes(' set '))));
}

// A confirmed change requires CAS response plus independent status readback.
{
  const doc=documentFixture(),commands=[]; let current={...state};
  const run=async command=>{commands.push(command);if(command.includes('susfs-runtime set uid-gating 0 41')) current={...state,enabled:14,generation:42};return JSON.stringify(command===READ_COMMANDS.owners?enabled:command===READ_COMMANDS.kernel?{susfs:{features:[]}}:current);};
  await startHub(doc,{confirm:()=>true},run);
  const input=inputFor(doc,'uid-gating');input.checked=false;await input.handlers.change();
  check(()=>assert.equal(commands.length,5));
  check(()=>assert.equal(commands.at(-1),READ_COMMANDS.runtime));
  check(()=>assert.equal(input.checked,false));
  check(()=>assert.match(doc.ids.get('message').textContent,/bestätigt/));
}

// Failed readback blocks further writes until refresh; cancel performs no write.
for (const cancel of [true,false]) {
  const doc=documentFixture(),commands=[];let readCount=0;
  const run=async command=>{commands.push(command);if(command===READ_COMMANDS.runtime&&++readCount>1)throw Error('readback failed');return JSON.stringify(command===READ_COMMANDS.owners?enabled:command===READ_COMMANDS.kernel?{susfs:{features:[]}}:state);};
  await startHub(doc,{confirm:()=>!cancel},run);const input=inputFor(doc,'uid-gating');input.checked=false;await input.handlers.change();
  check(()=>assert.equal(commands.length,cancel?3:5));
  check(()=>assert.equal(input.disabled,!cancel));
}

// KernelSU callback errors are surfaced, with callbacks removed after completion.
{
  const scope={ksu:{exec:(command,options,name)=>scope[name](0,'{}','')}};
  check(()=>assert.equal(typeof scope.ksu.exec,'function'));
  assert.equal(await bridge('status',scope),'{}');assertions++;
  check(()=>assert.equal(Object.keys(scope).length,1));
}
{
  const writes=[];const root={dataset:{},style:{setProperty:(...args)=>writes.push(args)}};
  applyAppearance({localStorage:{getItem:key=>key==='zeromount-theme'?'light':'#ab12ef'}},root);
  check(()=>assert.equal(root.dataset.zmTheme,'light'));check(()=>assert.deepEqual(writes,[['--zm-accent','#ab12ef']]));
  applyAppearance({localStorage:{getItem:()=>"url(javascript:bad)"}},root);
  check(()=>assert.equal(writes.length,1));
}
{
  const entry=createSusfsEntry(documentFixture());check(()=>assert.equal(entry.href,'./susfs-brene.html'));check(()=>assert.equal(entry.className,'settings__item zm-integration-entry'));
}
console.log(JSON.stringify({assertions,passed:true,opening_read_only:true,owner_gates:true,cas_and_readback:true}));
