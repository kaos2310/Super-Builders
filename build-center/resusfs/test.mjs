import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
const here=path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/,'$1'));
const legacy=process.argv[2];if(!legacy)throw new Error('Pass legacy ReSuSFS helper path');
let source=await readFile(path.join(decodeURI(here),'resusfs-path-filter.mjs'),'utf8');
source=source.replace("'./resusfs-runtime.mjs?r=2'",JSON.stringify(pathToFileURL(path.resolve(legacy,'resusfs-runtime.mjs')).href));
const {parseStatus,command,mount}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const state={schema:1,owner:'ReSuSFS',write_allowed:true,prerequisites_present:true,command_support_probed:false,kernel_readback_available:false,packages:'',revision:'none',selection_saved:false,saved_selection_valid:true};
assert.equal(command(state,' com.example.one , com.example.two '),"/data/adb/modules/ReSuSFS/bin/resusfs-path-filter set 'com.example.one,com.example.two' 'none'");
assert.equal(command(state,''),"/data/adb/modules/ReSuSFS/bin/resusfs-path-filter set '' 'none'");
for(const text of ["com.example.app';id",'com.app,$(id)','com.app\ncom.other','com.app,,com.other'])assert.throws(()=>command(state,text));
assert.throws(()=>command({...state,write_allowed:false},'com.example.app'));
assert.throws(()=>command({...state,prerequisites_present:false},'com.example.app'));
assert.throws(()=>parseStatus({...state,kernel_readback_available:true}));
assert.throws(()=>parseStatus({...state,revision:'$(id)'}));
class Element {
 children=[];handlers={};nodes=new Map();disabled=false;value='';textContent='';
 set innerHTML(text){this.html=text;for(const match of text.matchAll(/id="([^"]+)"/g))this.nodes.set(match[1],new Element());}
 querySelector(selector){return this.nodes.get(selector.slice(1));}
 append(node){this.children.push(node);}
 addEventListener(name,handler){this.handlers[name]=handler;}
}
const host=new Element(),commands=[],doc={createElement:()=>new Element()};let stored={...state},fail=false;
const result=mount(host,doc,{confirm:()=>true},async cmd=>{commands.push(cmd);if(cmd.endsWith(' status'))return JSON.stringify(stored);if(fail)throw new Error('Kernel command unsupported');stored={...state,packages:'com.example.one',revision:'123-16',selection_saved:true};return JSON.stringify({applied:true,saved:true,kernel_readback_available:false,revision:stored.revision});});
await new Promise(resolve=>setTimeout(resolve,0));
assert.deepEqual(commands,['/data/adb/modules/ReSuSFS/bin/resusfs-path-filter status']);
assert.equal(host.children.length,1);
assert.equal(result.section.id,'resusfs-path-filter-panel');
assert.match(result.section.html,/ausgewählte Apps sichtbar/);
result.section.querySelector('#rs-path-packages').value='com.example.one';
await result.section.querySelector('#rs-path-apply').handlers.click();
assert.equal(commands[1],"/data/adb/modules/ReSuSFS/bin/resusfs-path-filter set 'com.example.one' 'none'");
assert.equal(commands[2],'/data/adb/modules/ReSuSFS/bin/resusfs-path-filter status');
assert.match(result.section.querySelector('#rs-path-status').textContent,/Schreibaufruf vom Kernel bestätigt/);
fail=true;result.section.querySelector('#rs-path-packages').value='com.example.two';
await result.section.querySelector('#rs-path-apply').handlers.click();
assert.equal(result.section.querySelector('#rs-path-status').textContent,'Kernel command unsupported');
assert.equal(result.section.querySelector('#rs-path-apply').disabled,true);
console.log('ReSuSFS native UID UI: parser, injection rejection, ownership gates, additive mount, read-only open, saved-selection verification and unsupported-kernel error passed');
