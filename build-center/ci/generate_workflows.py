"""Create reviewable reusable workflows from the existing audited builder."""
from pathlib import Path
import argparse
import copy
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
if (ROOT/'.build-deps').exists():sys.path.insert(0,str(ROOT/'.build-deps'))
import yaml


class Loader(yaml.SafeLoader):
    yaml_implicit_resolvers=copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)
for key,resolvers in Loader.yaml_implicit_resolvers.items():
    Loader.yaml_implicit_resolvers[key]=[(tag,pattern) for tag,pattern in resolvers if tag!='tag:yaml.org,2002:bool']
Loader.add_implicit_resolver('tag:yaml.org,2002:bool',re.compile(r'^(?:true|false)$',re.I),list('tTfF'))


class Dumper(yaml.SafeDumper):pass
def represent_string(dumper,value):
    return dumper.represent_scalar('tag:yaml.org,2002:str',value,style='|' if '\n' in value else None)
Dumper.add_representer(str,represent_string)


def transform(value):
    if isinstance(value,str):
        return (value.replace('d7d042816b82b200c25b3a93dcc158ba0307cabf','${{ inputs.center_pin }}')
                .replace('d7d04281','${{ inputs.center_short }}')
                .replace('41165','${{ inputs.center_code }}')
                .replace('3980','${{ inputs.center_count }}'))
    if isinstance(value,list):return [transform(v) for v in value]
    if isinstance(value,dict):return {k:transform(v) for k,v in value.items()}
    return value


def generate(baseline,out):
    config=json.loads((ROOT/'config.json').read_text());out.mkdir(parents=True,exist_ok=True)
    mapping={
        'build-center-userspace.yml':'build-sukisu-41165-userspace.yml',
        'build-center-strict.yml':'build-sukisu-41165-kpm-strict.yml',
        'build-center-zeromount.yml':'build-zeromount-sukisu-41165.yml',
        'build-center-cache.yml':'cache-dependencies.yml',
        'build-center-resusfs.yml':'build-resusfs-41165-susfs240.yml'}
    for dest,source in mapping.items():
        workflow=transform(yaml.load((baseline/'.github/workflows'/source).read_text(encoding='utf-8'),Loader=Loader))
        workflow['name']='Build Center / '+dest.removeprefix('build-center-').removesuffix('.yml')
        call=workflow['on']['workflow_call']
        if call is None:call={};workflow['on']['workflow_call']=call
        workflow['on']={'workflow_call':call}
        inputs=call.setdefault('inputs',{})
        if 'resukisu_version_code' in inputs:
            if inputs['resukisu_version_code'].get('required'):
                inputs['resukisu_version_code'].pop('default',None)
            else:inputs['resukisu_version_code']['default']=''
        for definition in inputs.values():
            if 'description' in definition:
                definition['description']=re.sub(r'\$\{\{ inputs\.\w+ \}\}','selected source',definition['description'])
        for key in ('plan','pin','short','code','count'):
            inputs['center_'+key]={'type':'string','required':True}
        for job in workflow['jobs'].values():
            steps=job['steps'];checkout=next(s for s in steps if s.get('uses','').startswith('actions/checkout@'))
            for step in steps:
                if 'if' in step:
                    step['if']=step['if'].replace("'${{ inputs.center_code }}'",'inputs.center_code')
            location=checkout.get('with',{}).get('path','.')
            checkout.setdefault('with',{}).update(repository=config['repository'],ref=config['baseline_commit'],**{'persist-credentials':False})
            insert=[{'name':'Checkout Build Center controller','uses':'actions/checkout@v6',
                     'with':{'path':'.build-center','persist-credentials':False}},
                    {'name':'Prepare immutable update candidate','env':{'CENTER_PLAN':'${{ inputs.center_plan }}'},
                     'run':f'python3 "$GITHUB_WORKSPACE/.build-center/build-center/ci/bootstrap.py" {location}'}]
            steps[steps.index(checkout)+1:steps.index(checkout)+1]=insert
            if dest=='build-center-resusfs.yml':
                steps.insert(steps.index(insert[-1])+1,{'name':'Download the exact official SuSFS CLI sources',
                    'run':'python3 "$GITHUB_WORKSPACE/android14-6.1/build-helpers/_center_runtime.py" update-tool'})
            if dest=='build-center-strict.yml':
                runtime='$GITHUB_WORKSPACE/android14-6.1/build-helpers/_center_runtime.py'
                before=next(i for i,s in enumerate(steps) if s.get('name')=='Apply pinned SUSFS')
                steps.insert(before,{'name':'Prepare official pinned SuSFS delta',
                    'run':f'python3 "{runtime}" susfs-before --common "$KERNEL_ROOT/common"'})
                before=next(i for i,s in enumerate(steps) if s.get('name')=='Build Kernel')
                steps.insert(before,{'name':'Integrate official SuSFS updates and freeze final sources',
                    'run':'set -euo pipefail\n'+f'python3 "{runtime}" susfs-after --common "$KERNEL_ROOT/common" --ksu "$KERNEL_ROOT/$KSU_DIR"\n'+
                    f'python3 "{runtime}" capture-final --common "$KERNEL_ROOT/common" --ksu "$KERNEL_ROOT/$KSU_DIR"\n'})
                steps.append({'name':'Upload immutable plan and source manifests','if':'always()',
                    'uses':'actions/upload-artifact@v7','with':{'name':'Build-Center-Source-Evidence-${{ github.run_id }}',
                    'path':'.build-center-plan.json\n**/.build-center-source-manifest.json\n**/.build-center-susfs-update.json\n.build-center-susfs/upstream-changes.json',
                    'include-hidden-files':True,'if-no-files-found':'error','retention-days':30}})
        (out/dest).write_text(yaml.dump(workflow,Dumper=Dumper,sort_keys=False,width=140,allow_unicode=True),encoding='utf-8',newline='\n')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('baseline',type=Path);p.add_argument('--out',type=Path,default=ROOT/'integration/.github/workflows')
    a=p.parse_args();generate(a.baseline,a.out)
