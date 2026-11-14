import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const server=spawn('python',['-m','http.server','18944','--bind','127.0.0.1','--directory','web'],{cwd:root,windowsHide:true,stdio:'ignore'});
const base='http://127.0.0.1:18944';
const pin='d'.repeat(40),sus='6'.repeat(40),controller='c'.repeat(40);
const workflow=`ARGS+=(--expected-main-commit ${pin} --expected-main-code 41179)\nARGS+=(--expected-susfs-commit ${sus})`;
const encode=s=>Buffer.from(s).toString('base64');
let submitted=0,requestId='',done=false,artifact=false,moved=false,browser;
const run=()=>({id:submitted?9101:9100,status:done?'completed':'in_progress',conclusion:done?'success':null,head_branch:'codex/fixed',head_sha:controller,display_title:'SukiSU 41179 EZJ1 '+requestId,html_url:'https://github.com/kaos2310/Super-Builders/actions/runs/9100'});
const report={checks:[],pageErrors:[]};
async function response(b){
  if(b.url.includes('/commits/codex%2Fbuild-center-auto-updates'))return {status:404,data:{},headers:{}};
  if(b.method==='POST'){
    submitted++;requestId=b.data.inputs.request_id;assert.equal(b.data.ref,'codex/fixed');done=false;
    return {status:204,data:null};
  }
  let data,headers={};
  if(b.url.endsWith('/releases/latest'))data={tag_name:'v4.3.0-r2',assets:[]};
  else if(b.url.includes('SukiSU-Ultra/SukiSU-Ultra/commits?')){
    data=[{sha:pin}];headers.link='<https://api.github.com/repos/a/b/commits?per_page=1&page=3994>; rel="last"';
  }
  else if(b.url.includes('SukiSU-Ultra/SukiSU-Ultra/commits/'))data={sha:pin,commit:{message:'official main'}};
  else if(b.url.includes('contents/kernel/Kbuild'))data={content:encode('VERSION_BASE := 40000\nVERSION_OFFSET := 2815\nKSU_VERSION := $(shell expr $(VERSION_BASE) + $(LOCAL_COUNT) - $(VERSION_OFFSET))')};
  else if(b.url.includes('/files/'))data={content:encode('#define SUSFS_VERSION "v2.4.0"')};
  else if(b.url.includes('gitlab.com'))data={id:sus,title:'SUSFS 2.4.0'};
  else if(b.url.includes('/repos/kaos2310/Super-Builders/commits/'))data={sha:b.url.endsWith('/main')?'a'.repeat(40):controller};
  else if(b.url.includes('/contents/.github/'))data={encoding:'base64',content:encode(b.url.endsWith(controller)&&!moved?workflow:'python3 check_updates.py')};
  else if(b.url.endsWith('/actions/workflows/build-center.yml'))data={state:'active'};
  else if(b.url.includes('/actions/workflows/build-center.yml/runs'))data={workflow_runs:new URL(b.url).searchParams.get('branch')==='codex/fixed'?[run()]:[{head_branch:'main',display_title:'Build Center',status:'completed',conclusion:'success'},run()]};
  else if(b.url.includes('/jobs?'))data={jobs:[{name:'Kernel und Samsung Strict KMI / CRC',status:run().status,conclusion:done?(artifact?'success':'skipped'):null,steps:[]}]};
  else if(b.url.includes('/artifacts?'))data={artifacts:artifact?[{name:'S928BXXS6EZJ1-EUX-Strict-AnyKernel3-Flash',digest:'sha256:'+'e'.repeat(64),archive_download_url:'https://api.github.com/repos/kaos2310/Super-Builders/actions/artifacts/9/zip'}]:[]};
  else if(b.url.endsWith('/actions/runs/42129383180'))data={id:42129383180,status:'completed',conclusion:'success'};
  else if(/\/actions\/runs\/910[01]$/.test(b.url))data=run();
  else if(b.url.includes('/releases?')){
    const code=done&&artifact?41179:41178;
    data=[{tag_name:`s928b-ezj1-suki${code}-verified`,assets:[{name:'build-plan.json'},
      {name:`ReSuSFS-${code}.zip`,digest:'sha256:'+'f'.repeat(64),browser_download_url:`https://github.com/kaos2310/Super-Builders/releases/download/test/ReSuSFS-${code}.zip`}]}];
  }
  else throw Error('Uncovered native request: '+b.url);
  return {status:200,data,headers};
}
try{
  for(let i=0;i<50;i++){try{if((await fetch(base)).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const context=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block'});
  const page=await context.newPage();page.on('pageerror',e=>report.pageErrors.push(e.message));
  await page.exposeFunction('nativeTransport',response);
  await page.addInitScript(()=>{
    localStorage.setItem('center-settings',JSON.stringify({repository:'kaos2310/Super-Builders',ref:'main',channel:'main',auto:true}));
    window.KaosNative={loadToken:()=>'test-only-not-a-credential',storeToken:()=>{},request:(id,body)=>window.nativeTransport(JSON.parse(body)).then(value=>window.__nativeResult(id,value)).catch(e=>window.__nativeResult(id,{error:e.message}))};
  });
  await page.clock.install();await page.goto(base);
  await page.waitForFunction(()=>document.getElementById('ref').value==='codex/fixed'&&!document.getElementById('refresh').disabled);
  assert.match(await page.locator('#build-hint').textContent(),/41179.*codex\/fixed/);
  assert.match(await page.locator('#run-label').textContent(),/9100.*codex\/fixed/);
  assert.equal(await page.locator('#suki-sha').textContent(),pin.slice(0,12));
  report.checks.push('Saved main is migrated to the published controller matching both current source commits');
  await page.locator('#build').click();assert.equal(await page.locator('#build-dialog').isVisible(),false);assert.equal(submitted,0);
  assert.match(await page.locator('#message').textContent(),/läuft bereits/);
  report.checks.push('The existing matching build is followed without duplicate dispatch');
  done=true;artifact=true;await page.clock.runFor(16000);
  await page.waitForFunction(()=>document.getElementById('run-status').textContent==='KERNEL-ZIP BEREIT');
  assert.match(await page.locator('#download-list').textContent(),/ReSuSFS-41179\.zip/);
  assert.doesNotMatch(await page.locator('#download-list').textContent(),/ReSuSFS-41178\.zip/);
  report.checks.push('A completed build is confirmed only with the strict ZIP and checksum');
  report.checks.push('Completion refreshes matching release packages instead of retaining the older version');
  await page.locator('#build').click();assert.match(await page.locator('#plan-review').textContent(),new RegExp('Controller: '+controller));
  await page.locator('#confirm-build').click();await page.waitForFunction(()=>document.getElementById('run-label').textContent.includes('9101'));
  assert.equal(submitted,1);report.checks.push('Dispatch revalidates the controller and correlates the requested branch run');
  done=true;artifact=false;await page.clock.runFor(16000);
  await page.waitForFunction(()=>document.getElementById('run-status').textContent==='KEIN KERNEL GEBAUT');
  report.checks.push('A planning-only success is displayed as no kernel built');
  moved=true;await page.locator('#refresh').click();await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
  assert.equal(await page.locator('#build').isDisabled(),true);assert.match(await page.locator('#message').textContent(),/automatische Build-Integration/);
  report.checks.push('A missing matching controller disables dispatch despite the latest version being detected');
  assert.deepEqual(report.pageErrors,[]);report.checks.push('No Android-bridge JavaScript errors');
  await mkdir(path.join(root,'.test-results'),{recursive:true});
  await writeFile(path.join(root,'.test-results','native-browser-results.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
}finally{if(browser)await browser.close();server.kill();}
