"""Scheduled entry point on main dispatches the current immutable build controller."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from center_core import CenterError,request,resolve_sources
from ci.check_updates import recent_failure,verify_source_request
from ci.network import source_get
from ci.versioning import validate_mapping
from ci.published import matching_release


def run(repo,ref,controller_sha,channel='main',force=False,request_id='',source_request='',
        transport=request,resolver=resolve_sources,now=None,revision='hidden-name-readdir-v2'):
    if (not re.fullmatch(r'[\w.-]+/[\w.-]+',repo) or not re.fullmatch(r'[\w./-]{1,200}',ref)
            or not re.fullmatch('[0-9a-f]{40}',controller_sha)):
        raise ValueError('Invalid automatic repository/controller')
    def get(url,token=''):
        return source_get(url,token,requester=transport)
    token=os.environ.get('GH_TOKEN','')
    plan=resolver(channel,token,get=get);validate_mapping(plan)
    verify_source_request(plan,source_request,controller_sha)
    pair=plan['sukisu_commit'][:8]+'-'+plan['susfs_commit'][:8]
    result={'controller':controller_sha,'branch':ref,'pair':pair,'sukisu_code':plan['sukisu_code'],
            'sukisu_commit':plan['sukisu_commit'],'susfs_commit':plan['susfs_commit']}
    base='https://api.github.com/repos/'+repo
    runs=get(base+'/actions/workflows/build-center.yml/runs?per_page=100&branch='+urllib.parse.quote(ref,safe=''),token)['data']['workflow_runs']
    active=next((r for r in runs if r.get('head_branch')==ref and r.get('status')!='completed'),None)
    if active:return dict(result,outcome='waiting',run_id=active['id'])
    if not force:
        releases=get(base+'/releases?per_page=100',token)['data']
        existing=next((r for r in releases if matching_release(r,plan,revision)),None)
        if existing:return dict(result,outcome='current',release_url=existing.get('html_url',''))
        if recent_failure(repo,pair,token,get=get,now=now,controller_sha=controller_sha):
            return dict(result,outcome='cooldown',reason='This exact source/controller failed within 24 hours')
    # A branch may move while sources are resolved. Never dispatch an unreviewed
    # successor under the old source request; the next tick can check it afresh.
    head=get(base+'/commits/'+urllib.parse.quote(ref,safe=''),token)['data']['sha']
    if head!=controller_sha:raise ValueError('Automatic controller moved before dispatch')
    request_id=request_id or 'automatic-'+os.environ.get('GITHUB_RUN_ID','local')
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,100}',request_id):raise ValueError('Invalid automatic request ID')
    expected={k:plan[k] for k in ('sukisu_commit','sukisu_code','sukisu_count','susfs_commit')}
    expected.update(schema=1,channel=channel,controller_sha=controller_sha)
    if 'sukisu_version_formula' in plan:expected['sukisu_version_formula']=plan['sukisu_version_formula']
    response=transport(base+'/actions/workflows/build-center.yml/dispatches',token,method='POST',
        data={'ref':ref,'inputs':{'channel':channel,'force':str(force).lower(),'request_id':request_id,
                                'source_request':json.dumps(expected,separators=(',',':'))}})
    if response['status']!=204:raise CenterError('Automatic build submission was not confirmed')
    return dict(result,outcome='submitted',request_id=request_id)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--channel',choices=('main','release'),default='main')
    parser.add_argument('--force',action='store_true');parser.add_argument('--request-id',default='')
    args=parser.parse_args();root=Path(__file__).resolve().parents[2]
    config=json.loads((root/'build-center/config.json').read_text())
    sha=subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip()
    manifest=json.loads((root/'build-center/controller.json').read_text())
    for key,path in (('workflow_sha256','.github/workflows/build-center.yml'),
                     ('resolver_sha256','build-center/ci/check_updates.py')):
        if hashlib.sha256((root/path).read_bytes()).hexdigest()!=manifest[key]:
            raise RuntimeError('Automatic controller manifest drift: '+path)
    repo=os.environ.get('GITHUB_REPOSITORY',config['repository'])
    if repo!=config['repository']:raise ValueError('Automatic target differs from configured repository')
    if not config['automatic_builds'] and not args.force:result={'outcome':'disabled'}
    else:result=run(repo,config.get('automatic_controller_ref','codex/build-center-ezjb-auto-20261122'),sha,
        args.channel,args.force,args.request_id,os.environ.get('CENTER_SOURCE_REQUEST',''),
        revision=config.get('kernel_revision',''))
    Path('build-center-automatic.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as out:
            out.write('Build Center automatic check: **'+result['outcome']+'**\n\n')
            if result.get('request_id'):out.write('Build request: '+result['request_id']+'\n')
            if result.get('release_url'):out.write('Matching kernel: '+result['release_url']+'\n')


if __name__=='__main__':main()
