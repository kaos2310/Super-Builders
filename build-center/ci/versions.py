"""Reviewed upstream version formulas, including the official Nova rebrand."""
import re

REPOSITORY='SukiSU-Nova/SukiSU-Nova'
FORGEJO_REPOSITORY='shirkneko/SukiSU'
FORGEJO_URL='https://git.zako.shirkneko.top:20004/' + FORGEJO_REPOSITORY + '.git'
FORMULAS={'ultra':(40000,2815,'-'),'nova':(30000,996,'+')}

def official_nova_repository(plan):
    identity=(plan.get('sukisu_repository'), plan.get('sukisu_repository_url'))
    return identity in ((REPOSITORY, None), (FORGEJO_REPOSITORY, FORGEJO_URL))

def version_code(count,base,offset,operator):
    if type(count) is not int or count<2815:raise ValueError('Full upstream commit count is required')
    return base+count+(offset if operator=='+' else -offset)

def identify(kbuild,count):
    for family,(base,offset,operator) in FORMULAS.items():
        if (re.findall(r'^VERSION_BASE\s*:=\s*(\d+)\s*$',kbuild,re.M)==[str(base)] and
                re.findall(r'^VERSION_OFFSET\s*:=\s*(\d+)\s*$',kbuild,re.M)==[str(offset)] and
                f'expr $(VERSION_BASE) + $(LOCAL_COUNT) {operator} $(VERSION_OFFSET)' in kbuild):
            return {'sukisu_family':family,'sukisu_version_base':base,'sukisu_version_offset':offset,
                    'sukisu_version_operator':operator,'sukisu_code':version_code(count,base,offset,operator)}
    raise ValueError('Upstream version formula requires an explicit compatibility review')

def validate(plan):
    family=plan.get('sukisu_family','ultra')
    if family not in FORMULAS:raise ValueError('Unknown reviewed upstream family')
    base,offset,operator=FORMULAS[family]
    for key,expected in [('sukisu_version_base',base),('sukisu_version_offset',offset),('sukisu_version_operator',operator)]:
        if key in plan and plan[key]!=expected:raise ValueError('Invalid reviewed version formula metadata')
    if type(plan['sukisu_code']) is not int or plan['sukisu_code']!=version_code(plan['sukisu_count'],base,offset,operator):
        raise ValueError('Invalid source/version mapping')
    if family=='nova' and not official_nova_repository(plan):
        raise ValueError('Nova requires the canonical official repository')
