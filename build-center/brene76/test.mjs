import assert from 'node:assert/strict';
import {KEYS, STATUS_COMMAND, saveCommand, filterSaveCommand, formatReport, start, execReadOrSave} from './brene76.mjs';
let assertions=0;
const check=fn=>{fn();assertions++;};
const original=['shrink_buffer_size','spoof_hosts','spoof_libstagefright','hide_lineage_strings','disable_child_process_restrictions','hide_ksu_directories','hide_third_party_apps'];
for(const key of original) check(()=>assert(KEYS.includes(key)));
for(const key of KEYS) check(()=>assert.equal(saveCommand(key,true),`/data/adb/modules/meta-zeromount/bin/zm brene76 set ${key} true`));
for(const value of ['com.ok;reboot','$(id)','com.ok\ncom.bad',"com.ok'",'.','..','a'.repeat(256),'a'.repeat(65535)]) check(()=>assert.throws(()=>filterSaveCommand(value)));
check(()=>assert.equal(filterSaveCommand(' com.one, com.two,com.one, '),"/data/adb/modules/meta-zeromount/bin/zm brene76 filter-set 'com.one,com.two'"));
check(()=>assert.equal(filterSaveCommand(''),"/data/adb/modules/meta-zeromount/bin/zm brene76 filter-set ','"));
check(()=>assert.throws(()=>saveCommand('$(reboot)',true)));
check(()=>assert.throws(()=>formatReport({version:'0.0.75'})));
class Element {
  constructor(){this.children=[];this.handlers={};this.disabled=false;this.textContent='';this.checked=false;this.value='';}
  append(...children){this.children.push(...children);}
  addEventListener(name,handler){this.handlers[name]=handler;}
}
function fixture(){
  const ids=new Map(['refresh','message','kernel','peers','mounts','settings','filter-save','filter-packages'].map(id=>[id,new Element()]));
  return {getElementById:id=>ids.get(id),createElement:()=>new Element(),ids};
}
function report(){return {version:'0.0.76',settings:{values:Object.fromEntries(KEYS.map(key=>[key,key==='shrink_buffer_size'?'true':'false']))},sus_path_uid_filter_packages:','};}
const input=(doc,key)=>doc.ids.get('settings').children[KEYS.indexOf(key)].children[0];
{
  const doc=fixture(),commands=[],value=report();
  await start(doc,{confirm:()=>true},async command=>{commands.push(command);return JSON.stringify(value);});
  check(()=>assert.deepEqual(commands,[STATUS_COMMAND]));
  check(()=>assert.equal(doc.ids.get('settings').children.length,12));
  check(()=>assert.equal(doc.ids.get('filter-packages').disabled,false));
  for(const key of original) check(()=>assert.equal(input(doc,key).disabled,false));
}
// Saved options are read back; saving is not represented as a live kernel write.
{
  const doc=fixture(),commands=[],value=report();
  const run=async command=>{commands.push(command);if(command.includes(' set hide_vector_injection true'))value.settings.values.hide_vector_injection='true';return JSON.stringify(value);};
  await start(doc,{confirm:()=>true},run);input(doc,'hide_vector_injection').checked=true;
  await input(doc,'hide_vector_injection').handlers.change();
  check(()=>assert.equal(commands.length,3));check(()=>assert.equal(commands.at(-1),STATUS_COMMAND));
  check(()=>assert.equal(input(doc,'hide_vector_injection').checked,true));
  check(()=>assert(!commands.some(c=>c.includes('susfs-runtime')||c.includes(' late'))));
}
for(const cancel of [true,false]){
  const doc=fixture(),commands=[],value=report();
  const run=async command=>{commands.push(command);if(command.includes("filter-set 'com.visible'"))value.sus_path_uid_filter_packages='com.visible';return JSON.stringify(value);};
  await start(doc,{confirm:()=>!cancel},run);doc.ids.get('filter-packages').value='com.visible';
  await doc.ids.get('filter-save').handlers.click();
  check(()=>assert.equal(commands.length,cancel?1:3));
  if(!cancel)check(()=>assert.equal(doc.ids.get('filter-packages').value,'com.visible'));
}
// Invalid/corrupt/incomplete reads keep every mutation disabled.
for(const mutate of [v=>delete v.settings.values.spoof_hosts,v=>v.sus_path_uid_filter_packages="com.bad'",v=>v.version='0.0.75']){
  const doc=fixture(),value=report();mutate(value);
  await start(doc,{},async()=>JSON.stringify(value));
  check(()=>assert.equal(doc.ids.get('filter-save').disabled,true));
  for(const key of KEYS)check(()=>assert.equal(input(doc,key).disabled,true));
}
{
  const doc=fixture(),commands=[],value=report();let reads=0;
  await start(doc,{confirm:()=>true},async command=>{commands.push(command);if(command===STATUS_COMMAND&&++reads>1)throw Error('read failed');return JSON.stringify(value);});
  doc.ids.get('filter-packages').value='com.new';await doc.ids.get('filter-save').handlers.click();
  check(()=>assert.equal(commands.length,3));check(()=>assert.equal(doc.ids.get('filter-save').disabled,true));
}
{
  const scope={ksu:{exec:(command,options,name)=>scope[name](0,'{}','')}};
  check(()=>assert.equal(awaitableMarker(scope),true));
  assert.equal(await execReadOrSave('status',scope),'{}');assertions++;
  check(()=>assert.deepEqual(Object.keys(scope),['ksu']));
}
function awaitableMarker(scope){return typeof scope.ksu.exec==='function';}
console.log(JSON.stringify({assertions,passed:true,opening_read_only:true,original_options_preserved:true,saved_filter_readback:true,runtime_unchanged:true}));
