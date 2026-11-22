"""Recognize a completed release for the exact firmware and immutable sources."""
import re


def matching_release(release,plan,revision=''):
    tag=plan['release_tag']+('-'+revision if revision else '')
    firmware=plan.get('firmware','')
    if not re.fullmatch(r'S928B[A-Z0-9]+',firmware):return False
    body=release.get('body') or ''
    assets=release.get('assets') or []
    return (not release.get('draft')
            and re.fullmatch(re.escape(tag)+r'(?:-r[0-9]+)?',release.get('tag_name','')) is not None
            and 'SukiSU commit: '+plan['sukisu_commit'] in body
            and 'SuSFS commit: '+plan['susfs_commit'] in body
            and any(a.get('name')=='build-plan.json' for a in assets)
            and any(a.get('name','').endswith('AnyKernel3.zip') and firmware+'-EUX' in a['name']
                    and re.fullmatch('sha256:[0-9a-f]{64}',a.get('digest') or '') for a in assets))
