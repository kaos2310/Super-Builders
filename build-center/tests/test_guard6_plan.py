from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import unittest

APP=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(APP))
spec=importlib.util.spec_from_file_location('guard6_candidate',APP/'guard6/package.py')
guard=importlib.util.module_from_spec(spec);spec.loader.exec_module(guard)
PLAN=json.loads((Path(__file__).parent/'fixtures/guard6-plan-41181.json').read_text())


class GuardPlanTests(unittest.TestCase):
    def validate(self,plan,marker=None):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);helpers=root/'android14-6.1/build-helpers';helpers.mkdir(parents=True)
            (root/'.build-center-plan.json').write_text(json.dumps(plan if marker is None else marker))
            guard.validate(plan,helpers)

    def test_real_app_run_41181_pair_is_accepted(self):
        self.validate(dict(PLAN))

    def test_next_consistent_source_pair_uses_the_same_guard_controller(self):
        self.validate(dict(PLAN,sukisu_commit='a'*40,sukisu_code=41182,sukisu_count=3997,susfs_commit='b'*40))

    def test_release_channel_can_use_the_same_compatible_runtime_abi(self):
        plan=dict(PLAN,channel='release');plan.pop('sukisu_source_kind')
        self.validate(plan)

    def test_wrong_source_pair_cannot_reuse_prepared_helpers(self):
        for changes in ({'sukisu_commit':'a'*40},{'susfs_commit':'b'*40},{'controller_sha':'c'*40}):
            with self.subTest(changes=changes),self.assertRaisesRegex(RuntimeError,'another build plan'):
                self.validate(dict(PLAN,**changes),PLAN)

    def test_matching_marker_does_not_allow_an_invalid_plan_or_an_unsupported_abi(self):
        for changes in ({'sukisu_code':41180},{'sukisu_count':True},{'sukisu_commit':'main'},
                        {'susfs_commit':'short'},{'susfs_version':'v2.5.0'},{'profile':'wrong'},
                        {'firmware':'S928BXXU6EZIF'},{'sukisu_requested_ref':'a'*40},
                        {'sukisu_source_kind':'official-pull-request-merge-preview'},
                        {'controller_sha':'main'},{'source_request_schema':True}):
            with self.subTest(changes=changes),self.assertRaises(RuntimeError):self.validate(dict(PLAN,**changes))


if __name__=='__main__':unittest.main()
