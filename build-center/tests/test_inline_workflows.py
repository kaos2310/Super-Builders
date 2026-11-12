from pathlib import Path
import copy
import sys
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'build-center/ci'))
from inline_workflows import bind, expression, expand
from generate_workflows import Loader


class InlineWorkflowTests(unittest.TestCase):
    def test_boolean_and_string_inputs_remain_different(self):
        values = {'enabled': expression(False), 'word': expression('false')}
        self.assertEqual(bind('inputs.enabled || inputs.word', values, 'if'), "false || 'false'")
        self.assertEqual(bind('${{ inputs.enabled }}', values), '${{ false }}')

    def test_expression_and_literal_quoting(self):
        self.assertEqual(expression('${{ needs.resolve.outputs.pin }}'), 'needs.resolve.outputs.pin')
        self.assertEqual(expression("O'Reilly"), "'O''Reilly'")
        self.assertEqual(expression(''), "''")
        self.assertEqual(bind('literal inputs.enabled', {'enabled': 'false'}), 'literal inputs.enabled')

    def test_unbound_expression_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unbound input'):
            bind('${{ inputs.missing }}', {})

    def workflow(self):
        return yaml.load((ROOT / 'build-center/ci/compat/build-center-41178-reusable.yml').read_text(encoding='utf-8'), Loader=Loader)

    def test_all_original_jobs_steps_and_gate_dependencies_remain(self):
        original = self.workflow()
        result, counts = expand(original, ROOT)
        self.assertEqual(counts, {'dependencies': 14, 'userspace': 14, 'zeromount': 12, 'resusfs': 9, 'strict': 76})
        self.assertEqual(set(result['jobs']), set(original['jobs']))
        self.assertEqual(sum(len(j['steps']) for j in result['jobs'].values()), 132)
        self.assertEqual(result['jobs']['resolve'], original['jobs']['resolve'])
        self.assertEqual(result['jobs']['publish'], original['jobs']['publish'])
        for name in counts:
            self.assertEqual(result['jobs'][name]['needs'], original['jobs'][name]['needs'])
            self.assertEqual(result['jobs'][name]['if'], original['jobs'][name]['if'])
        self.assertNotIn('uses', result['jobs']['strict'])

    def test_active_main_build_retains_every_existing_build_and_publish_gate(self):
        original, _ = expand(self.workflow(), ROOT)
        active = yaml.load((ROOT / '.github/workflows/build-center.yml').read_text(encoding='utf-8'), Loader=Loader)
        self.assertEqual(set(active['jobs']), set(original['jobs']))
        for name in set(original['jobs']) - {'resolve','zeromount','publish'}:
            self.assertEqual(active['jobs'][name], original['jobs'][name], name)
        zero=copy.deepcopy(active['jobs']['zeromount'])
        additions=zero['steps'][12:]
        zero['steps']=zero['steps'][:12]
        self.assertEqual(zero,original['jobs']['zeromount'])
        self.assertEqual(len(additions),3)
        self.assertIn('guard6/test.py',additions[1]['run'])
        self.assertIn('guard6/package.py',additions[1]['run'])
        self.assertIn('ZeroMount-Guard6.13-BRENE75',additions[2]['with']['name'])
        publish=copy.deepcopy(active['jobs']['publish'])
        guard_download=publish['steps'].pop(3)
        self.assertEqual(publish,original['jobs']['publish'])
        self.assertEqual(guard_download['with']['path'],'guard6-files')
        resolver = active['jobs']['resolve']['steps'][1]['run']
        self.assertIn('--expected-main-code 41179', resolver)
        self.assertIn('--expected-main-commit dae36db016079546b9fc028636a3326d09979777', resolver)
        self.assertIn('--expected-susfs-commit 69b8e734920b8f9ed885ab8d112969719698e242',resolver)
        self.assertNotIn('--sukisu-ref', resolver)
        self.assertNotIn('41178', resolver)

    def test_effective_permissions_match_the_reviewed_callers(self):
        result, _ = expand(self.workflow(), ROOT)
        for name in ('userspace', 'zeromount', 'resusfs'):
            self.assertEqual(result['jobs'][name]['permissions'], {'contents': 'read'})
        self.assertEqual(result['jobs']['dependencies']['permissions'], {'contents': 'read', 'actions': 'write'})
        self.assertEqual(result['jobs']['strict']['permissions'], {'contents': 'write', 'actions': 'write'})

    def test_permission_increase_is_rejected(self):
        workflow = self.workflow()
        workflow['jobs']['strict']['permissions'] = {'contents': 'read', 'actions': 'read'}
        with self.assertRaisesRegex(ValueError, 'increase caller permission'):
            expand(workflow, ROOT)

    def test_missing_required_input_and_unknown_inputs_are_rejected(self):
        original = self.workflow()
        for change in ('missing', 'unknown'):
            workflow = copy.deepcopy(original)
            if change == 'missing':
                workflow['jobs']['userspace']['with'].pop('center_pin')
            else:
                workflow['jobs']['userspace']['with']['unexpected'] = 'value'
            with self.assertRaises(ValueError):
                expand(workflow, ROOT)

    def test_only_local_reviewed_workflows_are_supported(self):
        workflow = self.workflow()
        workflow['jobs']['userspace']['uses'] = 'other/repository/.github/workflows/build.yml@main'
        with self.assertRaisesRegex(ValueError, 'repository-local'):
            expand(workflow, ROOT)


if __name__ == '__main__':
    unittest.main()
