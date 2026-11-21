"""Rebind the audited userspace verifier to actual upstream version/package data."""
if __package__:
    from .versioning import validate_mapping
else:
    from versioning import validate_mapping


def once(text,before,after):
    if text.count(before)!=1:raise RuntimeError('Audited userspace identity helper anchor changed')
    return text.replace(before,after,1)


def prepare(helper,code,plan):
    formula=validate_mapping(plan);count=plan['sukisu_count']
    path=helper/f'verify-sukisu-{code}-userspace.py';text=path.read_text(encoding='utf-8')
    text=once(text,'import argparse,hashlib,json,subprocess',
        'import argparse,hashlib,json,subprocess,re\nfrom _center_versioning import formula_from_kbuild,version_code')
    setup=("\nbuild=(root/'kernel/Kbuild').read_text(encoding='utf-8')\n"
        +f"formula=formula_from_kbuild(build)\nif formula!={formula!r} or version_code({count},formula)!={code}:raise RuntimeError('Userspace/Kbuild version formula drift')\n"
        +"packages=re.findall(r'^KSU_PACKAGE_NAME\\s*\\?=\\s*(com\\.sukisu\\.(?:ultra|nova))\\s*$',build,re.M)\n"
        +"if len(packages)!=1:raise RuntimeError('Official userspace manager identity missing')\nmanager_package=packages[0]\n")
    text=once(text,'root=a.source.resolve()','root=a.source.resolve()'+setup)
    expression=f"{formula['base']} + {count} {formula['operation']} {formula['offset']}"
    text=once(text,f"'version_formula':'40000 + {count} - 2815'",f"'version_formula':{expression!r},'manager_package':manager_package")
    text=once(text,"paths=['Cargo.toml'","paths=['kernel/Kbuild','Cargo.toml'")
    text=once(text,f"(b'{code}',b'com.sukisu.ultra')",f"(b'{code}',manager_package.encode())")
    path.write_text(text,encoding='utf-8',newline='\n')
    uapi=helper/f'sukisu_{code}_uapi.py';text=uapi.read_text(encoding='utf-8')
    text=once(text,'import subprocess\n','import subprocess\nfrom _center_versioning import formula_from_kbuild,version_code\n')
    old=f"    if 40000 + int(git(source, 'rev-list', '--count', 'HEAD')) - 2815 != {code}:"
    new=("    formula=formula_from_kbuild(git(source,'show',PIN+':kernel/Kbuild').decode())\n"
         +f"    if version_code(int(git(source,'rev-list','--count','HEAD')),formula) != {code}:")
    uapi.write_text(once(text,old,new),encoding='utf-8',newline='\n')
    session=helper/f'su-session-{code}/apply.py';text=session.read_text(encoding='utf-8')
    text=once(text,'import sys\n',"import sys\nsys.path.insert(0,str(Path(__file__).resolve().parent.parent))\nfrom _center_versioning import formula_from_kbuild,version_code\n")
    text=once(text,'        version_offset = -2815\n        compiled_version = 40000 + commit_count + version_offset',
        "        formula=formula_from_kbuild(git(ksu,'show',RESUKISU_PIN+':kernel/Kbuild'))\n"
        "        version_offset=formula['offset'] if formula['operation']=='+' else -formula['offset']\n"
        "        compiled_version = version_code(commit_count,formula)")
    text=once(text,'resukisu_version_offset=version_offset,',"resukisu_version_base=formula['base'],resukisu_version_offset=version_offset,")
    session.write_text(text,encoding='utf-8',newline='\n')
