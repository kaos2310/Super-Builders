"""Expand local single-job calls without changing their commands or permissions.

The isolated 41178 branch uses this after GitHub repeatedly failed to start
the reusable-workflow graph before assigning any job. It does not remove gates.
"""
from pathlib import Path
import argparse
import copy
import json
import re
import yaml
from generate_workflows import Loader, Dumper

EXPRESSION = re.compile(r'\$\{\{\s*(.*?)\s*\}\}', re.S)
INPUT = re.compile(r'\binputs\.([A-Za-z_][A-Za-z_0-9]*)\b')


def expression(value):
    if isinstance(value, str):
        match = EXPRESSION.fullmatch(value)
        return match[1] if match else "'" + value.replace("'", "''") + "'"
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) in (int, float):
        return json.dumps(value)
    raise ValueError('Unsupported input value type')


def bind(value, bindings, key=None):
    if isinstance(value, dict):
        return {k: bind(v, bindings, k) for k, v in value.items()}
    if isinstance(value, list):
        return [bind(v, bindings) for v in value]
    if not isinstance(value, str):
        return value
    def replace(match):
        if match[1] not in bindings:
            raise ValueError('Unbound input: ' + match[1])
        return bindings[match[1]]
    value = EXPRESSION.sub(lambda m: '${{ ' + INPUT.sub(replace, m[1]) + ' }}', value)
    return INPUT.sub(replace, value) if key == 'if' else value


def expand(workflow, root):
    result = copy.deepcopy(workflow)
    counts = {}
    for name, caller in workflow['jobs'].items():
        if 'uses' not in caller:
            continue
        relative = caller['uses']
        if not relative.startswith('./.github/workflows/') or '..' in Path(relative).parts:
            raise ValueError('Only repository-local workflow calls may be expanded')
        callee = yaml.load((root / relative).read_text(encoding='utf-8'), Loader=Loader)
        if set(callee) - {'name', 'on', 'permissions', 'jobs'} or len(callee['jobs']) != 1:
            raise ValueError('Only reviewed single-job workflows without root defaults are supported')
        call = callee['on']['workflow_call']
        if call.get('outputs') or call.get('secrets'):
            raise ValueError('Workflow outputs/secrets require a separate mapping')
        supplied = caller.get('with', {})
        definitions = call.get('inputs', {})
        if set(supplied) - set(definitions):
            raise ValueError('Unknown supplied workflow input')
        bindings = {}
        for key, definition in definitions.items():
            if key not in supplied and definition.get('required'):
                raise ValueError('Required workflow input missing: ' + key)
            default = {'boolean': False, 'number': 0, 'string': ''}[definition['type']]
            bindings[key] = expression(supplied.get(key, definition.get('default', default)))
        original = next(iter(callee['jobs'].values()))
        if original.get('needs') or original.get('if') or original.get('uses'):
            raise ValueError('Nested job dependencies or conditions require a separate mapping')
        job = bind(original, bindings)
        for key in ('needs', 'if'):
            if key in caller:
                job[key] = copy.deepcopy(caller[key])
        job['permissions'] = copy.deepcopy(original.get('permissions', callee.get(
            'permissions', caller.get('permissions', workflow.get('permissions', {})))))
        allowed = caller.get('permissions', workflow.get('permissions', {}))
        levels = {'none': 0, 'read': 1, 'write': 2}
        if not isinstance(allowed, dict) or not isinstance(job['permissions'], dict):
            raise ValueError('Only explicit permission maps are supported')
        for scope, level in job['permissions'].items():
            if levels[level] > levels[allowed.get(scope, 'none')]:
                raise ValueError('Expanded job would increase caller permission: ' + scope)
        if INPUT.search(json.dumps(job)):
            raise ValueError('Unexpanded callee input')
        counts[name] = len(job['steps'])
        result['jobs'][name] = job
    return result, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('template', type=Path)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    workflow = yaml.load(args.template.read_text(encoding='utf-8'), Loader=Loader)
    result, counts = expand(workflow, args.root)
    args.output.write_text(yaml.dump(result, Dumper=Dumper, sort_keys=False,
                                   width=140, allow_unicode=True), encoding='utf-8', newline='\n')
    print(json.dumps({'expanded_steps_by_job': counts, 'jobs': len(result['jobs']),
                      'total_steps': sum(len(j['steps']) for j in result['jobs'].values()),
                      'workflow_calls_remaining': any('uses' in j for j in result['jobs'].values())}, indent=2))


if __name__ == '__main__':
    main()
