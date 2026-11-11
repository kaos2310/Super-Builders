"""Resolve current sources once, deduplicate and emit immutable CI outputs."""
import argparse
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import sys
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from center_core import CenterError, request, resolve_sources


def recent_failure(repo,pair,token='',get=request,now=None):
    now=now or datetime.now(timezone.utc)
    url=f'https://api.github.com/repos/{repo}/actions/artifacts?name=Build-Center-Plan-'+urllib.parse.quote(pair,safe='')+'&per_page=100'
    items=get(url,token)['data'].get('artifacts',[])
    items=[a for a in items if not a.get('expired') and a.get('workflow_run',{}).get('id')]
    if not items:return False
    artifact=max(items,key=lambda a:a['created_at'])
    age=(now-datetime.fromisoformat(artifact['created_at'].replace('Z','+00:00'))).total_seconds()
    if age<0 or age>=86400:return False
    run=get(f"https://api.github.com/repos/{repo}/actions/runs/{artifact['workflow_run']['id']}",token)['data']
    return run.get('status')=='completed' and run.get('conclusion') in ('failure','timed_out','cancelled')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--channel', choices=('main', 'release'), default='main')
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--sukisu-ref', help='Exact official repository commit for an explicit build request')
    args = parser.parse_args()
    config = json.loads((Path(__file__).resolve().parents[1] / 'config.json').read_text())
    scheduled = os.environ.get('GITHUB_EVENT_NAME') == 'schedule'
    if scheduled and not config['automatic_builds']:
        outputs = {'build': 'false', 'reason': 'Automatic builds are disabled'}
    else:
        token = os.environ.get('GH_TOKEN', '')
        plan = resolve_sources(args.channel, token, source_ref=args.sukisu_ref)
        if args.sukisu_ref == '1c9cca42f8049227d4eea20ab3979db3c5662a7d':
            if (plan['sukisu_code'], plan['sukisu_count']) != (41178, 3993):
                raise ValueError('The requested 41178 preview source/version mapping changed')
            plan['sukisu_source_kind'] = 'official-pull-request-merge-preview'
            plan['sukisu_pull_request'] = 'https://github.com/SukiSU-Ultra/SukiSU-Ultra/pull/1044'
        plan['baseline_commit'] = config['baseline_commit']
        plan['susfs_release_base'] = config['susfs_release_base']
        plan['susfs_functional_base'] = config['susfs_functional_base']
        plan['repository'] = os.environ.get('GITHUB_REPOSITORY', config['repository'])
        plan['run_id'] = os.environ.get('GITHUB_RUN_ID', '')
        plan['sukisu_short'] = plan['sukisu_commit'][:8]
        plan['pair_key'] = plan['sukisu_commit'][:8]+'-'+plan['susfs_commit'][:8]
        revision=config.get('kernel_revision','')
        if revision:
            if not re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,63}',revision):
                raise ValueError('Invalid downstream kernel revision')
            plan['kernel_revision']=revision
            plan['release_tag']+='-'+revision
        if args.force:
            plan['release_tag'] += '-r' + (plan['run_id'] or 'local')
        exists = False
        try:
            request(f"https://api.github.com/repos/{plan['repository']}/releases/tags/" +
                    urllib.parse.quote(plan['release_tag'], safe=''), token)
            exists = True
        except CenterError as exc:
            if 'nicht gefunden' not in str(exc):
                raise
        cooldown=not args.force and not exists and recent_failure(plan['repository'],plan['pair_key'],token)
        outputs = {'build': 'true' if args.force or (not exists and not cooldown) else 'false',
                   'plan': json.dumps(plan, separators=(',', ':')),
                   'code': str(plan['sukisu_code']), 'pin': plan['sukisu_commit'],
                   'count': str(plan['sukisu_count']), 'tag': plan['release_tag'],
                   'pair':plan['pair_key'],
                   'reason': 'Same source pair failed within 24 hours; use force to retry' if cooldown else
                       'Result already published' if exists and not args.force else 'New immutable source pair'}
        Path('build-plan.json').write_text(json.dumps(plan, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in outputs.items() if k != 'plan'}, indent=2))
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as f:
            for key, value in outputs.items():
                f.write(f'{key}={value}\n')


if __name__ == '__main__':
    main()
