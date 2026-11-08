export const CONTROL='/data/adb/modules/ReSuSFS/bin/resusfs-control';
export const FEATURES=Object.freeze([
 {key:'uid-gating',bit:1,title:'UID-Gated Hiding',detail:'Begrenzt die vorhandenen SUSFS-Verbraucher anhand der UID-Freigabe.'},
 {key:'hidden-name',bit:2,title:'Hidden-Name-Filter',detail:'Pausiert oder aktiviert den vorhandenen Namensfilter.'},
 {key:'unicode-filter',bit:4,title:'Unicode-Filter',detail:'Pausiert oder aktiviert den vorhandenen Unicode-Namensfilter.'},
 {key:'symbol-hiding',bit:8,title:'Kernel-Symbole verbergen',detail:'Pausiert oder aktiviert den vorhandenen Symbolfilter.'},
]);
const uint=n=>Number.isInteger(n)&&n>=0&&n<=0xffffffff;
export function runtimeState(value) {
 if(value?.protocol!=='kaoslab-susfs-runtime'||value.version!==1||value.size!==48||!uint(value.supported)||value.supported>15||!uint(value.enabled)||(value.enabled&~value.supported)||!uint(value.generation)||value.generation===0)throw new Error('Runtime ABI v1 nicht bestätigt');
 return value;
}
export function mayWrite(state) {
 return state?.schema===1&&state.owner==='ReSuSFS'&&state.owner_active===true&&state.write_allowed===true&&['v2.3.0','v2.4.0'].includes(state.kernel_version);
}
export function runtimeCommand(state,key,value) {
 const feature=FEATURES.find(f=>f.key===key),runtime=runtimeState(state?.runtime);
 if(!mayWrite(state)||!feature||typeof value!=='boolean'||!(runtime.supported&feature.bit))throw new Error('Laufzeit-Änderung durch Zuständigkeit oder Kernel-Funktionen gesperrt');
 return `${CONTROL} runtime-set ${key} ${value?1:0} ${runtime.generation}`;
}
export function normalizePackages(text) {
 if(typeof text!=='string')throw new Error('Paketliste ungültig');
 const value=text.split(',').map(s=>s.trim()).join(',');
 if(value.length>4096||(value!==''&&value.split(',').some(s=>s.length>255||!/^[_A-Za-z][_A-Za-z0-9]*(\.[_A-Za-z][_A-Za-z0-9]*)+$/.test(s))))throw new Error('Paketnamen durch Kommas trennen, zum Beispiel com.example.app');
 return value;
}
export function priorityCommand(state,text) {
 const value=normalizePackages(text),revision=state?.priority_revision;
 if(!mayWrite(state)||state.priority_supported!==true||typeof revision!=='string'||!/^(none|[0-9]+-[0-9]+)$/.test(revision))throw new Error('Priority-UID-Änderung nicht freigegeben');
 return `${CONTROL} priority-set '${value}' '${revision}'`;
}
let serial=0;
export function bridge(command,scope=globalThis) {
 return new Promise((resolve,reject)=>{
  if(typeof scope.ksu?.exec!=='function')return reject(new Error('Diese Seite im Root-Manager öffnen'));
  const name=`resusfs_runtime_${Date.now()}_${serial++}`;
  const cleanup=()=>{clearTimeout(timer);delete scope[name];};
  const timer=setTimeout(()=>{cleanup();reject(new Error('Zeitlimit: Status erneut lesen'));},15000);
  scope[name]=(code,stdout,stderr)=>{cleanup();Number(code)===0?resolve(String(stdout)):reject(new Error(String(stderr||stdout||`Exit ${code}`)));};
  try{scope.ksu.exec(command,'{}',name);}catch(error){cleanup();reject(error);}
 });
}
export async function readStatus(run=bridge,scope=globalThis) {
 const state=JSON.parse(await run(`${CONTROL} status`,scope));
 if(state?.schema!==1||state.owner!=='ReSuSFS'||typeof state.owner_active!=='boolean'||typeof state.write_allowed!=='boolean')throw new Error('Verwalterstatus nicht lesbar');
 if(state.runtime!==null)runtimeState(state.runtime);
 return state;
}
export function mountPanel(container,doc=document,scope=globalThis,run=bridge) {
 const panel=doc.createElement('section');panel.id='resusfs-runtime-panel';panel.className='rs-runtime-card';
 panel.innerHTML=`<div class="rs-heading"><div><h2 id="rs-supplement-title">Runtime &amp; Priority UID</h2><p id="rs-version">Status wird gelesen …</p></div><button type="button" id="rs-refresh">Aktualisieren</button></div><p class="rs-note">Zusätzliche Kernel-Funktionen. Die ursprünglichen SUSFS-Regeln und Bedienelemente bleiben auf der SUSFS-Seite verfügbar.</p><p id="rs-owner"></p><div id="rs-controls"></div><p class="rs-note">Änderungen wirken sofort und werden für diesen Verwalter gespeichert. Ohne eigene Auswahl bleiben die Kernel-Vorgaben erhalten. Beim Öffnen wird nur gelesen.</p><div class="rs-priority"><h3>Priority-UID-Filter</h3><label for="rs-packages">Paketnamen, durch Kommas getrennt</label><textarea id="rs-packages" rows="2" spellcheck="false" autocapitalize="off" placeholder="com.example.app,com.example.other"></textarea><button type="button" id="rs-priority-apply">Liste anwenden &amp; speichern</button><p class="rs-note">Eine leere Liste löscht den Filter. Der Kernel bietet für diese Liste keine eigene Leseabfrage; angezeigt wird die gespeicherte Auswahl.</p></div><p id="rs-message" role="status" aria-live="polite"></p>`;
 container.prepend(panel);
 const $=id=>panel.querySelector(`#${id}`),inputs=new Map();let state=null,busy=false;
 const message=text=>{$('rs-message').textContent=text;};
 const render=()=>{
  $('rs-refresh').disabled=busy;
  $('rs-version').textContent=state?`Kernel: ${state.kernel_version} · Runtime ${state.runtime?'ABI v1, Generation '+state.runtime.generation:'nicht verfügbar'}`:'Status nicht verfügbar';
  $('rs-owner').textContent=mayWrite(state)?'ReSuSFS ist der aktive SUSFS-Verwalter.':'Schreibzugriffe pausieren: ReSuSFS muss alleiniger aktiver SUSFS-Verwalter sein; ZeroMount-SUSFS muss ausgeschaltet bleiben.';
  for(const feature of FEATURES){const input=inputs.get(feature.key);input.checked=!!(state?.runtime?.enabled&feature.bit);input.disabled=busy||!mayWrite(state)||!state?.runtime||!(state.runtime.supported&feature.bit);}
  $('rs-packages').disabled=$('rs-priority-apply').disabled=busy||!mayWrite(state)||state?.priority_supported!==true;
  if(state&&!busy)$('rs-packages').value=state.priority_packages||'';
 };
 const refresh=async()=>{
  if(busy)return;busy=true;render();message('Lese aktuellen Status …');
  try{state=await readStatus(run,scope);message('Aktueller Zustand gelesen.');}
  catch(error){state=null;message(error.message);}finally{busy=false;render();}
 };
 for(const feature of FEATURES){
  const row=doc.createElement('label');row.className='rs-runtime-row';
  const text=doc.createElement('span'),title=doc.createElement('strong'),detail=doc.createElement('small'),input=doc.createElement('input');
  title.textContent=feature.title;detail.textContent=feature.detail;text.append(title,detail);input.type='checkbox';input.disabled=true;input.setAttribute('aria-label',feature.title);row.append(text,input);$('rs-controls').append(row);inputs.set(feature.key,input);
  input.addEventListener('change',async()=>{
   const desired=input.checked,previous=!!(state?.runtime?.enabled&feature.bit);let command;
   try{command=runtimeCommand(state,feature.key,desired);}catch(error){input.checked=previous;message(error.message);return;}
   if(!scope.confirm(`${feature.title} ${desired?'einschalten':'ausschalten'} und für den nächsten Start speichern?`)){input.checked=previous;return;}
   busy=true;render();
   try{
    const updated=runtimeState(JSON.parse(await run(command,scope))),verified=await readStatus(run,scope);
    if(!verified.runtime||updated.generation!==verified.runtime.generation||updated.enabled!==verified.runtime.enabled||!!(verified.runtime.enabled&feature.bit)!==desired)throw new Error('Änderung nicht bestätigt; Status neu laden');
    state=verified;message('Laufzeit-Zustand zurückgelesen und Auswahl gespeichert.');
   }catch(error){state=null;message(error.message);}finally{busy=false;render();}
  });
 }
 $('rs-priority-apply').addEventListener('click',async()=>{
  let command;try{command=priorityCommand(state,$('rs-packages').value);}catch(error){message(error.message);return;}
  if(!scope.confirm('Priority-UID-Liste anwenden und für den nächsten Start speichern? Eine leere Liste löscht den Filter.'))return;
  busy=true;render();
  try{const result=JSON.parse(await run(command,scope));if(result.applied!==true||result.saved!==true)throw new Error('Paketliste nicht bestätigt');state=await readStatus(run,scope);message('Paketliste gespeichert; Kernel hat den Schreibaufruf bestätigt. Eine unabhängige Kernel-Leseabfrage gibt es dafür nicht.');}
  catch(error){state=null;message(error.message);}finally{busy=false;render();}
 });
 $('rs-refresh').addEventListener('click',refresh);render();refresh();return{panel,refresh};
}
export function integrate(doc=document,scope=globalThis,run=bridge) {
 const container=doc.getElementById('content-container');if(!container)return;
 let supplement=null,opener=null,panel=null;
 const openSupplement=()=>{
  if(!supplement){
   supplement=doc.createElement('dialog');supplement.id='resusfs-runtime-dialog';supplement.className='rs-supplement-dialog';
   supplement.setAttribute('aria-labelledby','rs-supplement-title');
   const back=doc.createElement('button');back.type='button';back.id='resusfs-runtime-back';back.className='rs-runtime-back';back.textContent='← Zurück zu SUSFS';
   back.addEventListener('click',()=>supplement.close());
   const content=doc.createElement('div');content.className='rs-supplement-content';
   supplement.append(back,content);doc.body.append(supplement);
   supplement.addEventListener('close',()=>opener?.focus({preventScroll:true}));
   // Query only after explicitly opening the addition. Its errors are isolated.
   supplement.showModal();panel=mountPanel(content,doc,scope,run);
  }else{supplement.showModal();panel.refresh();}
 };
 const ensure=()=>{
  const selected=doc.querySelector('.bottom-bar-item[page="susfs"][selected]')||doc.body.classList.contains('page-susfs');
  const host=doc.getElementById('susfs-boxes');
  if(selected&&host&&!doc.getElementById('resusfs-runtime-open')){
   opener=doc.createElement('button');opener.type='button';opener.id='resusfs-runtime-open';opener.className='rs-runtime-open';
   opener.textContent='Runtime & Priority UID →';opener.setAttribute('aria-haspopup','dialog');
   opener.addEventListener('click',openSupplement);host.prepend(opener);
  }
 };
 new MutationObserver(ensure).observe(doc.body,{childList:true,subtree:true,attributes:true,attributeFilter:['selected','class']});
 doc.getElementById('susfs')?.addEventListener('click',()=>setTimeout(ensure,0));ensure();
}
if(typeof document!=='undefined')integrate();
