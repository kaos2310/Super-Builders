"""The app's reviewed source request must be enforced before any build starts."""
import copy
from contextlib import chdir, redirect_stdout
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci.check_updates import verify_source_request
from ci import check_updates


class SourceRequestTests(unittest.TestCase):
    def setUp(self):
        self.plan = {'channel':'main','sukisu_commit':'b'*40,'sukisu_code':41181,
                     'sukisu_count':3996,'susfs_commit':'c'*40}
        self.request = dict(self.plan,schema=1,controller_sha='a'*40)

    def check(self, request=None, plan=None, controller='a'*40):
        return verify_source_request(plan or self.plan,
                                     json.dumps(request if request is not None else self.request),controller)

    def test_reviewed_update_and_release_pair_are_accepted(self):
        self.check()
        self.check(dict(self.request,channel='release'),dict(self.plan,channel='release'))

    def test_unchanged_controller_can_accept_the_next_source_pair(self):
        plan = dict(self.plan,sukisu_code=41182,sukisu_count=3997,
                    sukisu_commit='d'*40,susfs_commit='e'*40)
        self.check(dict(plan,schema=1,controller_sha='a'*40),plan)

    def test_each_changed_source_field_is_rejected(self):
        for key,value in [('sukisu_commit','d'*40),('susfs_commit','e'*40),
                          ('sukisu_code',41182),('sukisu_count',3997),('channel','release')]:
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'source|version|channel'):
                self.check(plan=dict(self.plan,**{key:value}))

    def test_branch_movement_after_dispatch_is_rejected_in_ci(self):
        with self.assertRaisesRegex(ValueError,'controller'):
            self.check(controller='f'*40)

    def test_partial_invalid_and_inconsistent_requests_are_rejected(self):
        invalid = [dict(self.request,schema=2),dict(self.request,schema=True),
                   dict(self.request,sukisu_commit='main'),dict(self.request,sukisu_count=3995),
                   dict(self.request,sukisu_code='41181'),dict(self.request,controller_sha='')]
        for key in self.request:
            request = copy.copy(self.request); del request[key]; invalid.append(request)
        for request in invalid:
            with self.subTest(request=request),self.assertRaises(ValueError): self.check(request)
        for raw in ['null','[]','{invalid']:
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                verify_source_request(self.plan,raw,'a'*40)

    def test_scheduled_and_manual_latest_checks_can_resolve_without_an_app_request(self):
        verify_source_request(self.plan,'','a'*40)

    def test_cli_refuses_a_race_before_writing_plan_or_outputs(self):
        for field,value in [('sukisu_commit','d'*40),('susfs_commit','e'*40),('sukisu_count',3997)]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as tmp,chdir(tmp):
                env={'CENTER_SOURCE_REQUEST':json.dumps(self.request),'GITHUB_SHA':'a'*40,
                     'GITHUB_OUTPUT':str(Path(tmp)/'outputs')}
                with patch.dict(os.environ,env,clear=True),patch.object(sys,'argv',['check_updates.py']),\
                     patch.object(check_updates,'resolve_sources',return_value=dict(self.plan,**{field:value})),\
                     patch.object(check_updates,'request') as network:
                    with self.assertRaises(ValueError): check_updates.main()
                    network.assert_not_called()
                    self.assertFalse(Path('build-plan.json').exists())
                    self.assertFalse(Path('outputs').exists())

    def test_cli_writes_the_bound_plan_for_a_matching_app_request(self):
        plan=dict(self.plan,susfs_version='v2.4.0',release_tag='s928b-ezj1-suki41181-test')
        with tempfile.TemporaryDirectory() as tmp,chdir(tmp):
            env={'CENTER_SOURCE_REQUEST':json.dumps(self.request),'GITHUB_SHA':'a'*40,
                 'GITHUB_OUTPUT':str(Path(tmp)/'outputs')}
            with patch.dict(os.environ,env,clear=True),patch.object(sys,'argv',['check_updates.py']),\
                 patch.object(check_updates,'resolve_sources',return_value=plan),\
                 patch.object(check_updates,'request',side_effect=check_updates.CenterError('nicht gefunden')),\
                 patch.object(check_updates,'recent_failure',return_value=False),redirect_stdout(io.StringIO()):
                check_updates.main()
            result=json.loads(Path('build-plan.json').read_text())
            self.assertEqual(result['sukisu_commit'],self.request['sukisu_commit'])
            self.assertEqual(result['susfs_commit'],self.request['susfs_commit'])
            self.assertEqual(result['controller_sha'],self.request['controller_sha'])
            self.assertEqual(result['source_request_schema'],1)
            self.assertIn('build=true',Path('outputs').read_text())


if __name__=='__main__': unittest.main()
