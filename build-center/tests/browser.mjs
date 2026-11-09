import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const server=spawn('python',['desktop.py','--no-browser','--stay','--port','18943'],{cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});
let serverError='';server.stderr.on('data',d=>serverError+=d);
const base='http://127.0.0.1:18943';
let browser;
const report={checks:[],pageErrors:[]};
const pin='a'.repeat(40),susPin='b'.repeat(40);
const encode=s=>Buffer.from(s).toString('base64');
let dispatched=0,requestId='',failSources=false;
function response(url){
  if(url.endsWith('/releases/latest'))return {tag_name:'v4.3.0-r2',assets:[]};
  if(url.includes('SukiSU-Ultra/SukiSU-Ultra/commits?'))return {data:[{sha:pin}],headers:{link:'<https://api.github.com/repos/a/b/commits?per_page=1&page=3983>; rel="last"'}};
  if(url.includes('contents/kernel/Kbuild'))return {content:encode('VERSION_BASE := 40000\nVERSION_OFFSET := 2815\nKSU_VERSION := $(shell expr $(VERSION_BASE) + $(LOCAL_COUNT) - $(VERSION_OFFSET))')};
  if(url.includes('/files/'))return {content:encode('#define SUSFS_VERSION "v2.4.0"')};
  if(url.includes('gitlab.com'))return {id:susPin,title:'KernelSU: Sync with upstream'};
  if(url.includes('SukiSU-Ultra/SukiSU-Ultra/commits/'))return {sha:pin,commit:{message:failSources?'failure':'manager update'}};
  if(url.endsWith('/actions/workflows/build-center.yml'))return {state:'active'};
  if(url.includes('/actions/workflows/build-center.yml/runs'))return {workflow_runs:requestId?[{id:9001,status:'in_progress',head_branch:'main',head_sha:pin,display_title:'Build Center · '+requestId,html_url:'https://github.com/a/b/actions/runs/9001'}]:[]};
  if(url.includes('/jobs?'))return {jobs:[{name:'Offizielle Quellen prüfen',status:'completed',conclusion:'success',steps:[]},{name:'Kernel und Samsung Strict KMI / CRC',status:'in_progress',steps:[{name:'Build Kernel',status:'in_progress'}]}]};
  if(url.includes('/artifacts?'))return {artifacts:[]};
  if(url.endsWith('/actions/runs/42129383180'))return {id:42129383180,status:'completed',conclusion:'success',head_sha:pin};
  if(url.includes('/releases?'))return [];
  throw new Error('Uncovered API route: '+url);
}
try{
  for(let i=0;i<50;i++){try{const r=await fetch(base+'/api/info');if(r.ok)break;}catch{}await new Promise(r=>setTimeout(r,150));}
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  const context=await browser.newContext({viewport:{width:1440,height:1100},serviceWorkers:'block'});
  const page=await context.newPage();page.on('pageerror',e=>report.pageErrors.push(e.message));
  await page.route('**/api/proxy',async route=>{
    const b=route.request().postDataJSON();
    if(failSources&&b.url.includes('SukiSU-Ultra/SukiSU-Ultra/commits/'))return route.fulfill({json:{status:403,data:{},headers:{}}});
    if(b.method==='POST'){dispatched++;requestId=b.data.inputs.request_id;return route.fulfill({json:{status:204,data:null,headers:{}}});}
    const value=response(b.url);await route.fulfill({json:value.data?{status:200,...value}:{status:200,headers:{},data:value}});
  });
  await page.goto(base);await page.waitForFunction(()=>document.getElementById('suki-version').textContent.includes('41168'));
  await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
  assert.equal(await page.locator('#build').isDisabled(),true);report.checks.push('Sources resolve without token; dispatch remains disabled');
  await page.locator('#token').fill('test-only-not-a-real-token');await page.locator('#settings-form button[type=submit]').click();
  await page.waitForFunction(()=>!document.getElementById('build').disabled);
  const stored=await page.evaluate(()=>JSON.stringify(localStorage));assert.ok(!stored.includes('test-only-not-a-real-token'));report.checks.push('Web token never persists in localStorage');
  await page.locator('#build').click();assert.equal(await page.locator('#build-dialog').isVisible(),true);
  await page.locator('#build-dialog button[value=cancel]').click();assert.equal(dispatched,0);report.checks.push('Review and cancel do not dispatch a workflow');
  await page.locator('#build').click();await page.locator('#confirm-build').click();
  await page.waitForFunction(()=>document.getElementById('run-label').textContent.includes('9001'));
  assert.equal(dispatched,1);assert.match(await page.locator('#jobs').textContent(),/Build Kernel/);report.checks.push('Explicit dispatch follows its correlated run and displays job steps');
  failSources=true;await page.locator('#refresh').click();await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
  assert.equal(await page.locator('#build').isDisabled(),true);assert.match(await page.locator('#message').textContent(),/API-Limit/);report.checks.push('Failed source refresh disables build and does not report stale source as current');
  failSources=false;await page.locator('#refresh').click();await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
  await mkdir(path.join(root,'.test-results'),{recursive:true});
  await page.screenshot({path:path.join(root,'.test-results','desktop-test.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(root,'.test-results','mobile-test.png'),fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);assert.equal(overflow,false);report.checks.push('390px phone layout has no horizontal overflow');
  await page.locator('#forget').click();assert.equal(await page.locator('#token').inputValue(),'');assert.equal(await page.locator('#build').isDisabled(),true);report.checks.push('Token removal immediately revokes app dispatch capability');
  assert.deepEqual(report.pageErrors,[]);report.checks.push('No browser JavaScript errors');
  console.log(JSON.stringify(report,null,2));await writeFile(path.join(root,'.test-results','browser-results.json'),JSON.stringify(report,null,2));
}finally{if(browser)await browser.close();server.kill();if(serverError)console.error(serverError);}
