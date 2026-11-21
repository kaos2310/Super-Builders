import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {readVersionFormula,versionCode,validateSourceVersion} from '../web/versioning.js';

const fixture=name=>readFileSync(new URL('./fixtures/'+name,import.meta.url),'utf8');
test('actual Ultra and Nova Kbuild calculate the upstream version',()=>{
  assert.equal(versionCode(3998,readVersionFormula(fixture('kbuild-41183-upstream'))),41183);
  assert.equal(versionCode(4008,readVersionFormula(fixture('kbuild-nova-upstream'))),35004);
  assert.equal(versionCode(4009,readVersionFormula(fixture('kbuild-nova-upstream'))),35005);
});
test('new source arithmetic is validated as a whole, without evaluating shell text',()=>{
  const source=fixture('kbuild-nova-upstream');
  for(const text of [source+'\nVERSION_BASE := 30000',source+'\nKSU_VERSION := 123',
    source.replace('$(LOCAL_COUNT) + $(VERSION_OFFSET)','$(LOCAL_COUNT) + $(VERSION_OFFSET) + 1'),
    source.replace('$(LOCAL_COUNT) + $(VERSION_OFFSET)','$(LOCAL_COUNT) + $(VERSION_OFFSET); echo 1')])assert.throws(()=>readVersionFormula(text));
});
test('a source review retains count, formula and code together',()=>{
  const plan={sukisu_count:4008,sukisu_code:35004,sukisu_version_formula:readVersionFormula(fixture('kbuild-nova-upstream'))};
  validateSourceVersion(plan);
  assert.throws(()=>validateSourceVersion({...plan,sukisu_count:4009}));
  assert.throws(()=>validateSourceVersion({...plan,sukisu_code:41193}));
});
