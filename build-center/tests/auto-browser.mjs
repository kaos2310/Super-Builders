import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {mkdir,readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const server=spawn('python',['desktop.py','--no-browser','--stay','--port','18945'],{cwd:root,windowsHide:true,stdio:'ignore'});
const base='http://127.0.0.1:18945';
const workflow=await readFile(path.join(root,'../.github/workflows/build-center.yml'),'utf8');
const resolver=await readFile(path.join(root,'ci/check_updates.py'),'utf8');
const manifest=await readFile(path.join(root,'controller.json'),'utf8');
const legacy=await readFile(path.join(root,'tests/fixtures/legacy-controller.yml'),'utf8');
const branch='codex/build-center-auto-updates',oldBranch='codex/sukisu-41179-guard6-ezj1';
const controller='a'.repeat(40),oldController='9'.repeat(40),encode=s=>Buffer.from(s).toString('base64');
const ok=(data,headers={})=>({status:200,data,headers});
const file=s=>ok({encoding:'base64',content:encode(s)});
const report={checks:[],pageErrors:[]};
let browser;
try {
  for(let i=0;i<50;i++){try{if((await fetch(base+'/api/info')).ok)break;}catch{}await new Promise(r=>setTimeout(r,100));}
  browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  for(const native of [true,false]) {
    let code=41181,pin='b'.repeat(40),sus='c'.repeat(40),posted=[],run=null,moved=false;
    const response=async b=>{
      if(b.method==='POST') {
        assert.match(b.url,/\/actions\/workflows\/build-center.yml\/dispatches$/);
        posted.push(b.data);
        run={id:9201,status:'in_progress',conclusion:null,head_branch:branch,head_sha:controller,
          display_title:'Build Center EZJ1 · '+b.data.inputs.request_id,html_url:'https://github.com/kaos2310/Super-Builders/actions/runs/9201'};
        return {status:204,data:null,headers:{}};
      }
      if(b.url.endsWith('/releases/latest'))return ok({tag_name:'v4.3.0-r2',assets:[]});
      if(b.url.includes('SukiSU-Ultra/SukiSU-Ultra/commits?'))return ok([{sha:pin}],{link:`<https://api.github.com/repos/a/b/commits?per_page=1&page=${code-40000+2815}>; rel="last"`});
      if(b.url.includes('SukiSU-Ultra/SukiSU-Ultra/commits/'))return ok({sha:pin,commit:{message:'official source update'}});
      if(b.url.includes('contents/kernel/Kbuild'))return file('VERSION_BASE := 40000\nVERSION_OFFSET := 2815\nKSU_VERSION := $(shell expr $(VERSION_BASE) + $(LOCAL_COUNT) - $(VERSION_OFFSET))');
      if(b.url.includes('/files/'))return file('#define SUSFS_VERSION "v2.4.0"');
      if(b.url.includes('gitlab.com'))return ok({id:sus,title:'official SUSFS update'});
      if(b.url.includes('/repos/kaos2310/Super-Builders/commits/'))return ok({sha:b.url.endsWith(encodeURIComponent(branch))?(moved?'8'.repeat(40):controller):oldController});
      if(b.url.includes('/contents/.github/'))return file(b.url.endsWith(oldController)?legacy:workflow);
      if(b.url.includes('/contents/build-center/controller.json'))return file(manifest);
      if(b.url.includes('/contents/build-center/ci/check_updates.py'))return file(resolver);
      if(b.url.endsWith('/actions/workflows/build-center.yml'))return ok({state:'active'});
      if(b.url.includes('/actions/workflows/build-center.yml/runs'))return ok({workflow_runs:run?[run]:[]});
      if(b.url.endsWith('/actions/runs/9201'))return ok(run);
      if(b.url.includes('/jobs?'))return ok({jobs:[{name:'Kernel und Samsung Strict KMI / CRC',status:run.status,
        conclusion:run.status==='completed'?'skipped':null,steps:[]}]});
      if(b.url.includes('/artifacts?'))return ok({artifacts:[]});
      if(b.url.endsWith('/actions/runs/42129383180'))return ok({id:42129383180,status:'completed',conclusion:'success'});
      if(b.url.includes('/releases?'))return ok([]);
      throw Error('Uncovered API request: '+b.url);
    };
    const context=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block'});
    const page=await context.newPage();page.on('pageerror',e=>report.pageErrors.push(e.message));
    await page.exposeFunction('testTransport',response);
    await page.addInitScript(({native,oldBranch})=>{
      localStorage.setItem('center-settings',JSON.stringify({repository:'kaos2310/Super-Builders',ref:oldBranch,channel:'main',auto:true}));
      if(native)window.KaosNative={loadToken:()=>'test-only-not-a-credential',storeToken:()=>{},
        request:(id,body)=>window.testTransport(JSON.parse(body)).then(result=>window.__nativeResult(id,result)).catch(e=>window.__nativeResult(id,{error:e.message}))};
    },{native,oldBranch});
    await page.route('**/api/proxy',async route=>route.fulfill({json:await response(route.request().postDataJSON())}));
    await page.clock.install();await page.goto(base);
    await page.waitForFunction(()=>!document.getElementById('refresh').disabled&&document.getElementById('ref').value==='codex/build-center-auto-updates');
    if(!native) {
      assert.equal(await page.locator('#build').isDisabled(),true);
      await page.locator('#token').fill('test-only-not-a-credential');await page.locator('#settings-form button[type=submit]').click();
      await page.waitForFunction(()=>!document.getElementById('build').disabled);
    }
    assert.match(await page.locator('#build-hint').textContent(),/41181.*automatisch/);
    assert.equal(posted.length,0);
    const saved=await page.evaluate(()=>JSON.parse(localStorage.getItem('center-settings')));
    assert.equal(saved.ref,branch);assert.equal(saved.channel,'main');assert.equal(saved.auto,true);
    assert.ok(!(await page.evaluate(()=>JSON.stringify(localStorage))).includes('test-only-not-a-credential'));
    report.checks.push(`${native?'Android bridge':'Web'}: old 41179 setting migrates to an automatic controller before its first run, preserving preferences`);
    await page.locator('#build').click();assert.match(await page.locator('#plan-review').textContent(),/41181/);
    await page.locator('#build-dialog button[value=cancel]').click();assert.equal(posted.length,0);
    code=41182;pin='d'.repeat(40);sus='e'.repeat(40);
    await page.locator('#refresh').click();await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
    assert.match(await page.locator('#build-hint').textContent(),/41182.*automatisch/);
    assert.equal(await page.locator('#ref').inputValue(),branch);assert.equal(posted.length,0);
    await page.locator('#build').click();await page.locator('#confirm-build').click();
    await page.waitForFunction(()=>document.getElementById('run-label').textContent.includes('9201'));
    assert.equal(posted.length,1);
    assert.deepEqual(JSON.parse(posted[0].inputs.source_request),{schema:1,channel:'main',sukisu_commit:pin,
      sukisu_code:41182,sukisu_count:3997,susfs_commit:sus,controller_sha:controller});
    report.checks.push(`${native?'Android bridge':'Web'}: next SukiSU/SuSFS update uses the same branch and sends exactly the reviewed immutable pair`);
    await page.locator('#build').click();assert.equal(posted.length,1);assert.match(await page.locator('#message').textContent(),/läuft bereits/);
    run.status='completed';run.conclusion='success';await page.clock.runFor(16000);
    await page.waitForFunction(()=>document.getElementById('run-status').textContent==='KEIN KERNEL GEBAUT');
    report.checks.push(`${native?'Android bridge':'Web'}: no duplicate build and no false kernel success for a skipped run`);
    await page.locator('#build').click();code=41183;pin='f'.repeat(40);
    await page.evaluate(()=>document.getElementById('refresh').click());
    await page.waitForFunction(()=>!document.getElementById('refresh').disabled);
    await page.locator('#confirm-build').click();await page.waitForFunction(()=>document.getElementById('message').textContent.includes('seit der Bestätigung geändert'));
    assert.equal(posted.length,1);
    report.checks.push(`${native?'Android bridge':'Web'}: an update arriving during confirmation cannot replace the reviewed sources`);
    await page.locator('#build').click();moved=true;await page.locator('#confirm-build').click();
    await page.waitForFunction(()=>document.getElementById('message').textContent.includes('Controller wurde geändert'));
    assert.equal(posted.length,1);moved=false;
    report.checks.push(`${native?'Android bridge':'Web'}: a controller change is rejected before dispatch`);
    await page.locator('#channel').selectOption('release');await page.locator('#settings-form button[type=submit]').click();
    await page.waitForFunction(()=>!document.getElementById('build').disabled);
    await page.locator('#build').click();await page.locator('#confirm-build').click();
    await page.waitForFunction(()=>document.getElementById('message').textContent.includes('Build-Auftrag gesendet'));
    assert.equal(posted.length,2);assert.equal(JSON.parse(posted[1].inputs.source_request).channel,'release');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    report.checks.push(`${native?'Android bridge':'Web'}: release-channel binding and 390px layout pass`);
    await mkdir(path.join(root,'.test-results'),{recursive:true});
    await page.screenshot({path:path.join(root,'.test-results',native?'auto-android.png':'auto-web.png'),fullPage:true});
    await context.close();
  }
  assert.deepEqual(report.pageErrors,[]);
  await writeFile(path.join(root,'.test-results/automatic-browser-results.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
} finally { if(browser)await browser.close();server.kill(); }
