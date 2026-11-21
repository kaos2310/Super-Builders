from datetime import datetime,timezone
import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci.automatic import run,matching_release


class AutomaticDispatchTests(unittest.TestCase):
    def setUp(self):
        self.sha='c'*40;self.posts=[];self.runs=[];self.releases=[];self.failure=None
        self.plan={'channel':'main','sukisu_commit':'a'*40,'susfs_commit':'b'*40,'sukisu_code':35004,
            'sukisu_count':4008,'sukisu_version_formula':{'base':30000,'offset':996,'operation':'+'},
            'release_tag':'s928b-ezj1-suki35004-susfs2.4.0-aaaaaaaa-bbbbbbbb'}
        self.now=datetime(2026,11,20,20,tzinfo=timezone.utc)

    def transport(self,url,token='',method='GET',data=None,**kwargs):
        if method=='POST':self.posts.append(data);return {'status':204,'data':None,'headers':{}}
        if '/workflow' in url:result={'workflow_runs':self.runs}
        elif '/releases?' in url:result=self.releases
        elif '/artifacts?' in url:result={'artifacts':([{'created_at':'2026-11-20T19:30:00Z','workflow_run':{'id':7}}] if self.failure else [])}
        elif '/actions/runs/' in url:result=self.failure
        elif '/commits/' in url:result={'sha':self.sha}
        else:raise AssertionError(url)
        return {'status':200,'data':result,'headers':{}}

    def check(self,**kwargs):
        return run('kaos2310/Super-Builders','codex/build-center-auto-updates','c'*40,
            request_id='automatic-test',transport=self.transport,
            resolver=lambda *a,**k:copy.deepcopy(self.plan),now=self.now,**kwargs)

    def test_a_new_official_pair_dispatches_the_immutable_controller_once(self):
        result=self.check();self.assertEqual(result['outcome'],'submitted');self.assertEqual(len(self.posts),1)
        data=self.posts[0];self.assertEqual(data['ref'],'codex/build-center-auto-updates')
        request=json.loads(data['inputs']['source_request'])
        for key in ('sukisu_commit','susfs_commit','sukisu_count','sukisu_code','sukisu_version_formula'):
            self.assertEqual(request[key],self.plan[key])
        self.assertEqual(request['controller_sha'],'c'*40)
        self.assertEqual(data['inputs']['force'],'false')

    def test_running_build_prevents_another_submission(self):
        self.runs=[{'id':8,'head_branch':'codex/build-center-auto-updates','status':'in_progress'}]
        self.assertEqual(self.check()['outcome'],'waiting');self.assertEqual(self.posts,[])

    def test_exact_published_pair_prevents_a_new_build(self):
        self.releases=[{'tag_name':self.plan['release_tag']+'-hidden-name-readdir-v2-r123',
            'body':'SukiSU commit: '+'a'*40+'\nSuSFS commit: '+'b'*40,
            'assets':[{'name':'build-plan.json'},{'name':'S928BXXS6EZJ1-EUX-AnyKernel3.zip','digest':'sha256:'+'e'*64}]}]
        self.assertEqual(self.check()['outcome'],'current');self.assertEqual(self.posts,[])
        self.releases[0]['body']=self.releases[0]['body'].replace('b'*40,'d'*40)
        self.assertEqual(self.check()['outcome'],'submitted')

    def test_same_failed_controller_is_throttled_but_repaired_controller_retries(self):
        self.failure={'status':'completed','conclusion':'failure','head_sha':'c'*40}
        self.assertEqual(self.check()['outcome'],'cooldown');self.assertEqual(self.posts,[])
        self.failure['head_sha']='d'*40
        self.assertEqual(self.check()['outcome'],'submitted');self.assertEqual(len(self.posts),1)

    def test_moved_controller_is_rejected_before_post(self):
        self.sha='d'*40
        with self.assertRaisesRegex(ValueError,'moved'):self.check()
        self.assertEqual(self.posts,[])

    def test_failed_post_is_not_retried(self):
        transport=self.transport;calls=[]
        def failed(url,*args,**kwargs):
            if kwargs.get('method')=='POST':calls.append(url);raise ConnectionError('unconfirmed submission')
            return transport(url,*args,**kwargs)
        with self.assertRaises(ConnectionError):
            run('kaos2310/Super-Builders','codex/build-center-auto-updates','c'*40,
                request_id='automatic-test',transport=failed,resolver=lambda *a,**k:self.plan,now=self.now)
        self.assertEqual(len(calls),1)


if __name__=='__main__':unittest.main()
