import {Github, GH, selectKernelArtifact, selectReleaseAssets, assertRepository} from './api.js';

const $ = id => document.getElementById(id);
let token = '', sources = null, installed = null, activeRun = null, checking = false, pollBusy = false;
let api, localServer = false, nativeCounter = 0;
let lastBuildPoll = 0;
const nativePending = new Map();
window.__nativeResult = (id, result) => {
  const pending = nativePending.get(id); if (!pending) return;
  clearTimeout(pending.timer); nativePending.delete(id);
  result.error ? pending.reject(new Error(result.error)) : pending.resolve(result);
};
function nativeCall(method, body) {
  return new Promise((resolve,reject) => {
    const id = String(++nativeCounter);
    const timer = setTimeout(()=>{nativePending.delete(id);reject(new Error('Zeitüberschreitung. Bitte Verbindung prüfen.'));}, method === 'download' ? 600000 : 45000);
    nativePending.set(id, {resolve,reject,timer}); window.KaosNative[method](id, JSON.stringify(body));
  });
}
async function transport(body) {
  if (window.KaosNative) return nativeCall('request', body);
  if (localServer) {
    const response = await fetch('/api/proxy', {method:'POST',headers:{'Content-Type':'application/json','X-Center-Request':'1'},body:JSON.stringify(body),signal:AbortSignal.timeout(45000)});
    const result = await response.json(); if (result.error) throw new Error(result.error); return result;
  }
  const headers={Accept:'application/vnd.github+json'};
  if (body.token && new URL(body.url).hostname === 'api.github.com') headers.Authorization=`Bearer ${body.token}`;
  if (body.data) headers['Content-Type']='application/json';
  const r=await fetch(body.url,{method:body.method,headers,body:body.data?JSON.stringify(body.data):undefined,signal:AbortSignal.timeout(35000)});
  return {status:r.status,headers:Object.fromEntries(r.headers),data:r.status===204?null:await r.json()};
}
function message(text,error=false){$('message').textContent=text;$('message').className='message'+(error?' error':'');}
function openExternal(url){if(window.KaosNative)window.KaosNative.openExternal(url);else window.open(url,'_blank','noopener');}
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function pill(id,text,cls=''){$(id).textContent=text;$(id).className='pill '+cls;}
function makeApi(){api=new Github(transport,token,$('repository').value.trim());}
function settings(){return {repository:$('repository').value.trim(),ref:$('ref').value.trim(),channel:$('channel').value,auto:$('auto-check').checked};}
function saveSettings(){const value=settings();assertRepository(value.repository);localStorage.setItem('center-settings',JSON.stringify(value));}
function showSources(s){
  sources=s;$('suki-version').replaceChildren(node('span',String(s.sukisu_code)),node('small',s.sukisu_tag+' · '+s.channel));
  $('sus-version').replaceChildren(node('span',s.susfs_version),node('small','Android 14 · Linux 6.1'));
  $('suki-message').textContent=s.sukisu_message;$('sus-message').textContent=s.susfs_message;
  $('suki-sha').textContent=s.sukisu_commit.slice(0,12);$('sus-sha').textContent=s.susfs_commit.slice(0,12);$('channel-label').textContent=s.channel;
  pill('suki-pill','QUELLE AKTUELL');pill('sus-pill','QUELLE AKTUELL');
}
function installationState(value){
  installed=value;
  const ready=Boolean(value&&value.state==='active');
  $('build-hint').textContent=ready?'Workflow eingerichtet · Updates in GitHub Actions integrieren':value?'Workflow ist deaktiviert. Auf GitHub aktivieren.':'Build-Center-Workflow muss einmalig im Repository eingerichtet werden.';
  $('build').disabled=!ready||!sources||!token;
  pill('connection-state',ready?(token?'VERBUNDEN':'WORKFLOW BEREIT'):'EINRICHTUNG OFFEN',ready?'':'neutral');
}
function row(title,sub,buttonText,action,type='ZIP'){
  const div=node('div',undefined,'download-row');const info=node('div',undefined,'download-info');
  info.append(node('b',title),node('small',sub));const button=node('button',buttonText,'button secondary');
  button.addEventListener('click',async()=>{button.disabled=true;try{await action();}catch(e){message(e.message,true);}finally{button.disabled=false;}});
  div.append(node('span',type,'download-icon'),info,button);return div;
}
async function download(url,filename,digest='',kind='file'){
  const body={url,filename,digest,kind,token:new URL(url).hostname==='api.github.com'?token:''};
  if(kind==='kernel-artifact'&&!token)throw new Error('Für Actions-Artefakte ist ein GitHub-Token mit Actions-Leserecht erforderlich.');
  message(`Download wird geladen und geprüft: ${filename}`);
  let result;
  if(window.KaosNative){result=await nativeCall('download',body);}
  else if(localServer){
    const r=await fetch('/api/download',{method:'POST',headers:{'Content-Type':'application/json','X-Center-Request':'1'},body:JSON.stringify(body),signal:AbortSignal.timeout(600000)});
    result=await r.json();if(result.error)throw new Error(result.error);
    const a=node('a');a.href=result.href;a.download=result.filename;a.click();
  }else{
    if(kind==='kernel-artifact'){
      const id=url.match(/artifacts\/(\d+)/)?.[1];
      if(!id)throw new Error('Ungültige Artefakt-Adresse.');
      openExternal(`https://github.com/${api.repo}/actions/runs/${activeRun?.id||42129383180}/artifacts/${id}`);
      message('GitHub-Download geöffnet. Für automatische Prüfsumme und Entpacken die lokale Web-App, Windows-App oder Android-App verwenden.');return;
    }
    const a=node('a');a.href=url;a.target='_blank';a.rel='noopener';a.download=filename;a.click();
    message('Download geöffnet. Die SHA-256-Angabe steht am Paket.');return;
  }
  message(`${result.filename} bereitgestellt.\nSHA-256: ${result.sha256}`+(result.install?'\nAndroid-Paketinstaller wird geöffnet.':''));
}
let downloadRows=[];
function renderDownloads(){const list=$('download-list');if(downloadRows.length)list.replaceChildren(...downloadRows);}
async function loadDownloads(){
  const rows=[];
  if(sources){
    if(sources.manager){const a=sources.manager;rows.push(row(`SukiSU-Manager ${sources.sukisu_code}`,`Offizielle APK · ${a.digest||'Prüfsumme wird nach dem Download berechnet'}`,window.KaosNative?'Installieren':'Download',()=>download(a.browser_download_url,a.name,a.digest||'','apk'),'APK'));}
    else rows.push(row(`Manager passend zu ${sources.sukisu_code}`, 'Für diesen Entwicklungsstand ist noch keine passende Release-APK veröffentlicht.','Upstream öffnen',()=>openExternal('https://github.com/SukiSU-Ultra/SukiSU-Ultra/actions'),'APK'));
    rows.push(row(`SuSFS ${sources.susfs_version} · offizieller Quellcode`,`${sources.susfs_commit.slice(0,12)} · gki-android14-6.1 · Quellarchiv`, 'Download',()=>download(sources.susfs_source_url,`SuSFS-${sources.susfs_version}-${sources.susfs_commit.slice(0,8)}-sources.zip`)));
  }
  try{
    const allReleases=await api.releases();
    const releases=selectReleaseAssets(allReleases);
    const release=releases[0];
    if(release){for(const a of release.assets.filter(a=>a.name.endsWith('.zip')||a.name.endsWith('.apk')||a.name==='SHA256SUMS.txt')){
      rows.unshift(row(a.name,`${release.tag_name} · ${a.digest||'SHA256SUMS.txt im Release'}`,'Download',()=>download(a.browser_download_url,a.name,a.digest||'',a.name.endsWith('.apk')?'apk':'file'),a.name.endsWith('.apk')?'APK':'ZIP'));
    }}
    else if(api.repo==='kaos2310/Super-Builders'&&allReleases.some(r=>r.tag_name==='s928b-ezif-sukisu41165-susfs240-20261108'&&!r.draft)){
      const baseline=allReleases.find(r=>r.tag_name==='s928b-ezif-sukisu41165-susfs240-20261108'&&!r.draft);
      for(const a of baseline.assets.filter(a=>a.digest?.startsWith('sha256:')&&a.name.endsWith('.zip')&&(a.name.includes('AnyKernel3')||a.name.startsWith('ReSuSFS-')))){
        rows.unshift(row('Referenz · '+a.name,`Vorhandener Stand 41165 / SuSFS 2.4.0 · ${a.digest}`,'Download',()=>download(a.browser_download_url,a.name,a.digest)));
      }
    }else {
      const run=await api.run(42129383180),artifact=selectKernelArtifact(await api.artifacts(run.id),run);
      if(artifact)rows.unshift(row('Referenz-Kernel · SukiSU 41150 · Strict KMI', `Erfolgreicher Lauf ${run.id} · ${artifact.digest} · ursprüngliche Version`, 'Download',()=>download(artifact.archive_download_url,artifact.name+'.zip',artifact.digest,'kernel-artifact')));
    }
  }catch(e){rows.push(row('Kernel-Downloads bei GitHub',e.message,'Öffnen',()=>openExternal(`https://github.com/${api.repo}/actions`)));}
  downloadRows=rows;renderDownloads();
}
async function refresh(){
  if(checking)return;checking=true;$('refresh').disabled=true;$('refresh').textContent='↻  Wird geprüft …';
  try{makeApi();const results=await Promise.allSettled([api.sources($('channel').value),api.installation()]);
    if(results[0].status==='fulfilled')showSources(results[0].value);else{sources=null;pill('suki-pill','PRÜFUNG FEHLGESCHLAGEN','bad');pill('sus-pill','NICHT BESTÄTIGT','bad');}
    if(results[1].status==='fulfilled')installationState(results[1].value);else{installationState(null);}
    const failure=results.find(r=>r.status==='rejected');
    if(failure)message(failure.reason.message,true);else{message(installed?'Quellen geprüft. Der Build pinnt beide Quellen beim Start erneut.':'Quellen geprüft. Die lokale App ist bereit; die GitHub-Integration ist noch nicht eingerichtet.');}
    $('last-check').textContent='Geprüft: '+new Date().toLocaleString('de-DE');
    await loadDownloads();
    if(installed&&!pendingRequest&&(!activeRun||activeRun.status==='completed')){const runs=await api.runs();if(runs.length)await followRun(runs[0]);}
  }catch(e){message(e.message,true);}finally{checking=false;$('refresh').disabled=false;$('refresh').textContent='↻  Updates prüfen';}
}
const stateNames={completed:'Abgeschlossen',in_progress:'Läuft',queued:'In Warteschlange',waiting:'Wartet',pending:'Vorgemerkt',requested:'Angefordert'};
function runStatus(run){return run.status==='completed'?({success:'ERFOLGREICH',failure:'FEHLGESCHLAGEN',cancelled:'ABGEBROCHEN',skipped:'ÜBERSPRUNGEN',timed_out:'ZEITLIMIT'})[run.conclusion]||run.conclusion:stateNames[run.status]?.toUpperCase()||run.status;}
async function followRun(run){
  lastBuildPoll=Date.now();
  activeRun=run;localStorage.setItem('center-run',JSON.stringify({repo:api.repo,id:run.id}));
  $('run-link').href=run.html_url;$('run-label').textContent=`Lauf ${run.id} · ${run.head_branch} · ${run.head_sha.slice(0,8)}`;
  pill('run-status',runStatus(run),run.status==='completed'?(run.conclusion==='success'?'':'bad'):'running');
  const jobs=await api.jobs(run.id),list=$('jobs');list.replaceChildren();
  for(const job of jobs){const li=node('li');const detail=node('div');detail.append(node('b',job.name),node('small',job.steps?.find(s=>s.status==='in_progress')?.name||stateNames[job.status]||job.status));li.append(node('span',job.conclusion==='success'?'✓':job.conclusion==='failure'?'!':'·','job-marker'),detail,node('span',job.conclusion||stateNames[job.status]||job.status,'job-state'));list.append(li);}
  if(!jobs.length)list.append(node('li','GitHub plant die ersten Jobs …'));
  if(run.status==='completed'&&run.conclusion==='success'){
    const artifact=selectKernelArtifact(await api.artifacts(run.id),run);
    if(artifact){const key='run-'+run.id;if(!downloadRows.some(r=>r.dataset.run===key)){const r=row(`Kernel-ZIP aus Lauf ${run.id}`,artifact.name+' · '+artifact.digest,'Download',()=>download(artifact.archive_download_url,artifact.name+'.zip',artifact.digest,'kernel-artifact'));r.dataset.run=key;downloadRows.unshift(r);renderDownloads();}}
  }
}
let pendingRequest=null;
async function poll(){
  if(pollBusy||document.hidden)return;
  if(!token&&!pendingRequest&&lastBuildPoll&&Date.now()-lastBuildPoll<300000)return;
  lastBuildPoll=Date.now();pollBusy=true;
  try{
    if(pendingRequest){const run=await api.findRun(pendingRequest.id);if(run){pendingRequest=null;localStorage.removeItem('center-pending');await followRun(run);}else if(Date.now()-pendingRequest.time>600000){message('GitHub hat noch keinen passenden Lauf gemeldet. Vor einem erneuten Start die Actions-Seite prüfen.',true);pendingRequest=null;localStorage.removeItem('center-pending');}}
    else if(activeRun&&activeRun.status!=='completed')await followRun(await api.run(activeRun.id));
  }catch(e){message(e.message,true);}finally{pollBusy=false;}
}
$('refresh').addEventListener('click',refresh);
$('settings-form').addEventListener('submit',async event=>{event.preventDefault();try{token=$('token').value.trim();saveSettings();if(window.KaosNative)window.KaosNative.storeToken($('remember-token').checked?token:'');sources=null;activeRun=null;makeApi();await refresh();}catch(e){message(e.message,true);}});
$('forget').addEventListener('click',()=>{token='';$('token').value='';if(window.KaosNative)window.KaosNative.storeToken('');makeApi();installationState(installed);message('Token entfernt. Öffentliche Lesezugriffe bleiben verfügbar.');});
$('build').addEventListener('click',()=>{
  if(!sources)return;
  if(pendingRequest){message('Ein Build-Auftrag wartet bereits auf seine GitHub-Lauf-ID.');return;}
  $('plan-review').textContent=`SukiSU ${sources.sukisu_code}\n${sources.sukisu_commit}\n\nSuSFS ${sources.susfs_version}\n${sources.susfs_commit}\n\nProfil: S928BXXU6EZIF / EUX / 6.1.162\nDie Pipeline liest beim Start den neuesten Stand erneut ein.`;
  $('build-dialog').showModal();
});
$('build-dialog').addEventListener('close',async()=>{if($('build-dialog').returnValue!=='build')return;
  $('build').disabled=true;try{
    const id=await api.dispatch($('ref').value.trim(),$('channel').value,$('force-build').checked);
    pendingRequest={id,time:Date.now(),repo:api.repo};localStorage.setItem('center-pending',JSON.stringify(pendingRequest));
    activeRun=null;message('Build-Auftrag gesendet. Warte auf den zugehörigen GitHub-Lauf …');pill('run-status','AUFTRAG GESENDET','running');await poll();
  }catch(e){message(e.message,true);}finally{installationState(installed);}
});
for(const a of document.querySelectorAll('nav a'))a.addEventListener('click',()=>{document.querySelectorAll('nav a').forEach(n=>n.classList.remove('active'));a.classList.add('active');});
document.addEventListener('click',event=>{const a=event.target.closest('a');if(window.KaosNative&&a?.target==='_blank'&&a.href.startsWith('https://')){event.preventDefault();openExternal(a.href);}});
async function init(){
  try{const s=JSON.parse(localStorage.getItem('center-settings')||'null');if(s){$('repository').value=s.repository;$('ref').value=s.ref;$('channel').value=s.channel;$('auto-check').checked=s.auto;}}catch{}
  if(window.KaosNative){$('platform').textContent='ANDROID APP';$('remember-label').classList.remove('hidden');token=window.KaosNative.loadToken();$('token').value=token;$('remember-token').checked=Boolean(token);}
  else{try{const r=await fetch('/api/info',{signal:AbortSignal.timeout(1500)});if(r.ok){const info=await r.json();localServer=info.app==='SukiSU Build Center';$('platform').textContent=info.mode==='windows'?'WINDOWS APP':'WEB APP';}}catch{}}
  makeApi();
  try{const saved=JSON.parse(localStorage.getItem('center-run')||'null');if(saved?.repo===api.repo)await followRun(await api.run(saved.id));pendingRequest=JSON.parse(localStorage.getItem('center-pending')||'null');if(pendingRequest?.repo!==api.repo)pendingRequest=null;}catch{}
  $('build').disabled=true;await refresh();
  setInterval(poll,15000);
  setInterval(()=>{if($('auto-check').checked&&!document.hidden)refresh();},15*60000);
  if(localServer)setInterval(()=>fetch('/api/heartbeat',{method:'POST',headers:{'X-Center-Request':'1'}}).catch(()=>{}),30000);
  if('serviceWorker' in navigator&&!window.KaosNative)navigator.serviceWorker.register('./sw.js').catch(()=>{});
}
init();
