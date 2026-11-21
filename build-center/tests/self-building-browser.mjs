import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const server=spawn('python',['desktop.py','--no-browser','--stay','--port','18946'],{cwd:root,windowsHide:true,stdio:'ignore'});
const base='http://127.0.0.1:18946',branch='codex/build-center-ezjb-auto-20261122';
const workflow=await readFile(path.join(root,'../.github/workflows/build-center.yml'),'utf8');
const resolver=await readFile(path.join(root,'ci/check_updates.py'),'utf8');
const manifest=await readFile(path.join(root,'controller.json'),'utf8');
const nova=await readFile(path.join(root,'tests/fixtures/kbuild-nova-upstream'),'utf8');
const file=s=>({status:200,data:{encoding:'base64',content:Buffer.from(s).toString('base64')},headers:{}});
const ok=data=>({status:200,data,headers:{}});
const report={checks:[],pageErrors:[]};let browser;
try {
  for(let i=0;i<50;i++){try{if((await fetch(base+'/api/info')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  for(const native of [true,false]) {
    let count=3998,pin='b'.repeat(40),controller='a'.repeat(40),runs=[],posted=[];
    let sus='c'.repeat(40);
    const response=async b=>{
      if(b.method==='POST') {
        assert.match(b.url,/\/actions\/workflows\/build-center.yml\/dispatches$/);
        posted.push(b.data);
        runs.unshift({id:9300+posted.length,status:'in_progress',conclusion:null,head_branch:branch,head_sha:controller,
          display_title:'Build Center EZJB · '+b.data.inputs.request_id,html_url:'https://github.com/kaos2310/Super-Builders/actions/runs/'+(9300+posted.length)});
        return {status:204,data:null,headers:{}};
      }
      if(b.url.endsWith('/repositories/957055748'))return ok({id:957055748,full_name:'SukiSU-Nova/SukiSU-Nova'});
      if(b.url.endsWith('/releases/latest'))return ok({tag_name:'v3.0.0',assets:[]});
      if(b.url.includes('repositories/957055748/commits?'))return {...ok([{sha:pin}]),headers:{link:`<https://api.github.com/repos/a/b/commits?per_page=1&page=${count}>; rel="last"`}};
      if(b.url.includes('repositories/957055748/commits/'))return ok({sha:pin,commit:{message:'official update'}});
      if(b.url.includes('contents/kernel/Kbuild'))return file(count>=4008?nova:'VERSION_BASE := 40000\nVERSION_OFFSET := 2815\nKSU_VERSION := $(shell expr $(VERSION_BASE) + $(LOCAL_COUNT) - $(VERSION_OFFSET))');
      if(b.url.includes('/files/'))return file('#define SUSFS_VERSION "v2.4.0"');
      if(b.url.includes('gitlab.com'))return ok({id:sus,title:'official SUSFS update'});
      if(b.url.includes('/repos/kaos2310/Super-Builders/commits/'))return ok({sha:controller});
      if(b.url.includes('/contents/.github/'))return file(workflow);
      if(b.url.includes('/contents/build-center/controller.json'))return file(manifest);
      if(b.url.includes('/contents/build-center/ci/check_updates.py'))return file(resolver);
      if(b.url.endsWith('/actions/workflows/build-center.yml'))return ok({state:'active'});
      if(b.url.includes('/actions/workflows/build-center.yml/runs'))return ok({workflow_runs:runs});
      if(b.url.includes('/jobs?'))return ok({jobs:[]});
      if(b.url.includes('/artifacts?'))return ok({artifacts:[]});
      if(b.url.endsWith('/actions/runs/42129383180'))return ok({id:42129383180,status:'completed',conclusion:'success'});
      if(/\/actions\/runs\/930\d$/.test(b.url))return ok(runs.find(r=>b.url.endsWith('/'+r.id)));
      if(b.url.includes('/releases?'))return ok([]);
      throw Error('Uncovered request: '+b.url);
    };
    const context=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block'});
    const page=await context.newPage();page.on('pageerror',e=>report.pageErrors.push(e.message));
    await page.exposeFunction('testTransport',response);
    await page.addInitScript(({native,branch})=>{
      if(!localStorage.getItem('center-settings'))localStorage.setItem('center-settings',JSON.stringify({repository:'kaos2310/Super-Builders',ref:branch,channel:'main',auto:true}));
      if(native)window.KaosNative={loadToken:()=>'test-only-not-a-credential',storeToken:()=>{},
        request:(id,body)=>window.testTransport(JSON.parse(body)).then(result=>window.__nativeResult(id,result)).catch(e=>window.__nativeResult(id,{error:e.message}))};
    },{native,branch});
    await page.route('**/api/proxy',async route=>route.fulfill({json:await response(route.request().postDataJSON())}));
    await page.goto(base);await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
    if(!native){assert.equal(posted.length,0);await page.locator('#token').fill('test-only-not-a-credential');await page.locator('#settings-form button[type=submit]').click();}
    await page.waitForFunction(()=>document.getElementById('run-label').textContent.includes('9301'));
    assert.equal(posted.length,1);assert.equal(await page.locator('#build-dialog').isVisible(),false);
    assert.equal(JSON.parse(posted[0].inputs.source_request).sukisu_code,41183);
    await page.locator('#refresh').click();await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
    assert.equal(posted.length,1);
    runs[0].status='completed';runs[0].conclusion='failure';
    count=4008;pin='d'.repeat(40);
    await page.locator('#refresh').click();await page.waitForFunction(()=>document.getElementById('run-label').textContent.includes('9302'));
    assert.equal(posted.length,2);
    const request=JSON.parse(posted[1].inputs.source_request);
    assert.equal(request.sukisu_code,35004);assert.equal(request.sukisu_count,4008);assert.equal(request.sukisu_commit,pin);
    assert.deepEqual(request.sukisu_version_formula,{base:30000,offset:996,operation:'+'});
    assert.equal(await page.locator('#build-dialog').isVisible(),false);
    report.checks.push(`${native?'Android bridge':'Web'}: version-scheme change 41183 to Nova 35004 builds the exact pair automatically without a dialog`);
    runs[0].status='completed';runs[0].conclusion='failure';
    await page.locator('#refresh').click();await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
    await page.reload();await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
    if(!native){await page.locator('#token').fill('test-only-not-a-credential');await page.locator('#settings-form button[type=submit]').click();await page.waitForFunction(()=>!document.getElementById('refresh').disabled);}
    assert.equal(posted.length,2);
    report.checks.push(`${native?'Android bridge':'Web'}: refresh and app reload retain duplicate protection after failure`);
    controller='e'.repeat(40);
    await page.locator('#refresh').click();await page.waitForFunction(()=>document.getElementById('run-label').textContent.includes('9303'));
    assert.equal(posted.length,3);assert.equal(JSON.parse(posted[2].inputs.source_request).controller_sha,controller);
    runs[0].status='completed';runs[0].conclusion='success';
    sus='7'.repeat(40);
    await page.locator('#refresh').click();await page.waitForFunction(()=>document.getElementById('run-label').textContent.includes('9304'));
    assert.equal(posted.length,4);
    const susfsOnly=JSON.parse(posted[3].inputs.source_request);
    assert.equal(susfsOnly.sukisu_commit,pin);assert.equal(susfsOnly.sukisu_code,35004);assert.equal(susfsOnly.susfs_commit,sus);
    report.checks.push(`${native?'Android bridge':'Web'}: a SuSFS-only commit automatically starts integration with the unchanged SukiSU pin`);
    runs[0].status='completed';runs[0].conclusion='success';
    await page.locator('#auto-check').uncheck();await page.locator('#settings-form button[type=submit]').click();
    await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
    count=4009;pin='f'.repeat(40);
    await page.locator('#refresh').click();await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
    assert.equal(posted.length,4);assert.match(await page.locator('#suki-version').textContent(),/35005/);
    await page.locator('#build').click();assert.equal(await page.locator('#build-dialog').isVisible(),true);
    await page.locator('#build-dialog button[value=cancel]').click();
    report.checks.push(`${native?'Android bridge':'Web'}: repaired controller retries once; disabling automation preserves manual control for the next version`);
    assert.ok(!(await page.evaluate(()=>JSON.stringify(localStorage))).includes('test-only-not-a-credential'));
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await context.close();
  }
  assert.deepEqual(report.pageErrors,[]);
  await mkdir(path.join(root,'.test-results'),{recursive:true});
  await writeFile(path.join(root,'.test-results/self-building-browser-results.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
} finally {if(browser)await browser.close();server.kill();}
