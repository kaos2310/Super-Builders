import {test} from 'node:test';
import assert from 'node:assert/strict';
import {Github, apiError} from '../web/api.js';

const pin = 'f'.repeat(40);
const ok = data => ({status:200, headers:{}, data});
const missing = {status:422, headers:{}, data:{message:'No commit found for SHA: kaos2310'}};

test('connection check rejects a username entered as the workflow branch', async () => {
  const api = new Github(async b => b.url.endsWith('/commits/kaos2310') ? missing : ok({state:'active'}));
  await assert.rejects(() => api.installation('kaos2310'), /Workflow-Branch.*kaos2310.*main/);
});

test('invalid workflow branch is rejected before any build is submitted', async () => {
  let submitted = 0;
  const api = new Github(async b => {
    if (b.method === 'POST') { submitted++; return {status:204}; }
    return missing;
  }, 'test-only-not-a-credential');
  await assert.rejects(() => api.dispatch('kaos2310','main'), /Workflow-Branch.*kaos2310/);
  assert.equal(submitted,0);
});

test('valid branch is trimmed, verified and sent with the selected update channel', async () => {
  const calls = [];
  const api = new Github(async b => {
    calls.push(b);
    return b.method === 'POST' ? {status:204} : ok({sha:pin});
  }, 'test-only-not-a-credential');
  const id = await api.dispatch(' main ','release');
  assert.match(calls[0].url,/\/commits\/main$/);
  assert.equal(calls[1].data.ref,'main');
  assert.equal(calls[1].data.inputs.channel,'release');
  assert.equal(calls[1].data.inputs.request_id,id);
});

test('token denial during branch validation is not mislabeled as a missing branch', async () => {
  const api = new Github(async () => ({status:401,headers:{}}), 'test-only-not-a-credential');
  await assert.rejects(() => api.dispatch('main','main'), /Token ungültig/);
});

test('branch deletion after a successful connection check is caught before dispatch', async () => {
  let removed = false, submitted = 0;
  const api = new Github(async b => {
    if (b.url.endsWith('/actions/workflows/build-center.yml')) return ok({state:'active'});
    if (b.method === 'POST') { submitted++; return {status:204}; }
    return removed ? missing : ok({sha:pin});
  }, 'test-only-not-a-credential');
  assert.equal((await api.installation('main')).state,'active');
  removed = true;
  await assert.rejects(() => api.dispatch('main','main'), /Workflow-Branch.*main/);
  assert.equal(submitted,0);
});

test('known dispatch rejections give an actionable diagnosis without echoing the payload', () => {
  assert.match(apiError(422,{}, {message:'No ref found for: kaos2310'}),/Branch.*main/);
  assert.match(apiError(422,{}, {message:"Workflow does not have 'workflow_dispatch' trigger"}),/manuellen Start/);
  assert.match(apiError(422,{}, {message:'Unexpected inputs provided: [secret-like-value]'}),/Workflow-Eingaben/);
  assert.ok(!apiError(422,{}, {message:'Unexpected inputs provided: [secret-like-value]'}).includes('secret-like-value'));
});
