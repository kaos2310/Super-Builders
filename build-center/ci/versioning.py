"""Read the version arithmetic from an immutable upstream Kbuild, never eval it."""
from pathlib import Path
import re
import subprocess

LEGACY_FORMULA={'base':40000,'offset':2815,'operation':'-'}


def formula_from_kbuild(text):
    values={}
    for name,key in (('VERSION_BASE','base'),('VERSION_OFFSET','offset')):
        lines=re.findall(r'^'+name+r'\s*:=\s*([^\r\n]+)$',text,re.M)
        if len(lines)!=1 or not re.fullmatch(r'[0-9]+\s*(?:#.*)?',lines[0]):
            raise ValueError('Ambiguous upstream version assignment: '+name)
        values[key]=int(lines[0].split('#',1)[0].strip())
    lines=re.findall(r'^KSU_VERSION\s*:=\s*([^\r\n]+)$',text,re.M)
    if len(lines)!=1:raise ValueError('Ambiguous upstream version expression')
    shell=r'\$\(shell\s+expr\s+\$\(VERSION_BASE\)\s*\+\s*\$\(LOCAL_COUNT\)\s*([+-])\s*\$\(VERSION_OFFSET\)\s*\)'
    value=lines[0].split('#',1)[0].strip()
    match=re.fullmatch(shell,value) or re.fullmatch(r'\$\(if\s+\$\(LOCAL_COUNT\)\s*,\s*'+shell+r'\s*,\s*\$\(VERSION_BASE\)\s*\)',value)
    if match is None:raise ValueError('Unsupported upstream version arithmetic')
    values['operation']=match[1]
    version_code(2000000,values)
    return values


def version_code(count,formula=None):
    formula=LEGACY_FORMULA if formula is None else formula
    if (not isinstance(formula,dict) or set(formula)!={'base','offset','operation'}
            or type(count) is not int or not 1<=count<=2000000
            or any(type(formula[k]) is not int or not 0<=formula[k]<=1000000 for k in ('base','offset'))
            or formula['operation'] not in ('+','-')):
        raise ValueError('Invalid source/version mapping')
    code=formula['base']+count+(formula['offset'] if formula['operation']=='+' else -formula['offset'])
    if not 1<=code<=2147483647:raise ValueError('Invalid source/version mapping result')
    return code


def validate_mapping(plan):
    formula=plan.get('sukisu_version_formula',LEGACY_FORMULA)
    if type(plan.get('sukisu_code')) is not int or version_code(plan.get('sukisu_count'),formula)!=plan['sukisu_code']:
        raise ValueError('Invalid source/version mapping')
    return formula


def configure_identity(root,plan,verify=False):
    """Freeze exact code/count/tag and remove both old and new remote fallbacks."""
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args])
    pin=plan['sukisu_commit'];validate_mapping(plan)
    if git('rev-parse','HEAD').decode().strip()!=pin:raise RuntimeError('Wrong SukiSU pin')
    if int(git('rev-list','--count','HEAD'))!=plan['sukisu_count']:raise RuntimeError('SukiSU source count mismatch')
    original=git('show',pin+':kernel/Kbuild').decode()
    if formula_from_kbuild(original)!=validate_mapping(plan):raise RuntimeError('Pinned upstream version formula changed')
    packages=re.findall(r'^KSU_PACKAGE_NAME\s*\?=\s*(com\.sukisu\.(?:ultra|nova))\s*$',original,re.M)
    certificate='947ae944f3de4ed4c21a7e4f7953ecf351bfa2b36239da37a34111ad29993eef'
    if len(packages)!=1 or certificate not in original:raise RuntimeError('Official SukiSU manager identity lost')
    path=Path(root)/'kernel/Kbuild';text=path.read_text(encoding='utf-8')
    settings={'LOCAL_COUNT':str(plan['sukisu_count']),'KSU_VERSION':str(plan['sukisu_code']),
              'VERSION_TAG':plan['sukisu_tag'].removeprefix('v'),
              'KSU_VERSION_FULL':plan['sukisu_tag']+'-'+str(plan['sukisu_code'])+'-'+pin[:8]}
    for name in ('KSU_GITHUB_VER','GITHUB_COMMITS','KSU_RELEASE_VER','RELEASE_COMMITS'):
        count=len(re.findall(r'^'+name+r'\s*:=',original,re.M))
        if count>1:raise RuntimeError('Ambiguous remote version fallback: '+name)
        if count:settings[name]=''
    for name,value in settings.items():
        pattern=r'^'+name+r'\s*:=.*$';replacement=name+' := '+value
        if verify:
            if len(re.findall(pattern,text,re.M))!=1 or replacement not in text:
                raise RuntimeError('Kernel identity drift: '+name)
        else:
            text,count=re.subn(pattern,lambda _:replacement,text,flags=re.M)
            if count!=1:raise RuntimeError('Ambiguous Kbuild assignment: '+name)
    if packages[0] not in text or certificate not in text:raise RuntimeError('Official manager identity drift')
    if not verify:path.write_text(text,encoding='utf-8',newline='\n')
