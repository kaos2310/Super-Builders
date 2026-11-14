"""Prepare audited control overlays for both legacy and updated SUSFS sources."""
from pathlib import Path
import shutil


def once(text,old,new):
    if text.count(old)!=1:raise RuntimeError('Audited SUSFS helper anchor changed')
    return text.replace(old,new)


def bind_source_pair(helper,code,plan):
    # These controls run only after the official delta was merged and its
    # measured release receipt verified. Their exact-pin checks and receipts
    # must identify that effective source, while retaining historical mappings.
    session=helper/f'su-session-{code}/apply.py'
    session.write_text(once(session.read_text(),
        'SUSFS_PIN = "'+plan['susfs_functional_base']+'"',
        'SUSFS_PIN = "'+plan['susfs_commit']+'"'),encoding='utf-8',newline='\n')
    uid=helper/'susfs-uid-gated/apply.py'
    uid.write_text(once(uid.read_text(),'def susfs_pin(ksu):\n',
        'def susfs_pin(ksu):\n    if source_pin(ksu) == '+repr(plan['sukisu_commit'])+': return '+repr(plan['susfs_commit'])+'\n'),
        encoding='utf-8',newline='\n')


def prepare(helper,code,plan=None):
    release=helper/f'susfs-runtime-{code}/release240.py'
    original=release.read_text()
    if "EXPECTED = 'b3de6f8bba7b0c2adf63e4fb9777ccb2dc2916790b8fd085e8723e60f6dec25d'" not in original:
        raise RuntimeError('Audited release helper changed')
    shutil.copyfile(Path(__file__).with_name('release_identity.py'),release)
    uid=helper/'susfs-uid-gated/apply.py';text=uid.read_text()
    old='    guard("susfs_is_inode_sus_path", "\\tif (!susfs_is_current_proc_umounted_app()) {")'
    new=('    a,b=body_span(files["fs/susfs.c"],"susfs_is_inode_sus_path")\n'
         '    path_body=files["fs/susfs.c"][a:b]\n'
         '    path_anchor="\\tif (!susfs_is_current_proc_umounted_app()) {"\n'
         '    if path_anchor not in path_body:path_anchor="\\tif (uid < 10000) {"\n'
         '    guard("susfs_is_inode_sus_path",path_anchor)')
    text=once(text,old,new)
    old='edit("fs/susfs.c", "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\\n", feature + "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\\n",'
    new='edit("fs/susfs.c", "\\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH\\n", "\\n" + feature + "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\\n",'
    uid.write_text(once(text,old,new),encoding='utf-8',newline='\n')
    runtime=helper/f'susfs-runtime-{code}/apply.py';text=runtime.read_text()
    text=once(text,'    from release240 import EXPECTED\n    release=json.loads((common/\'.susfs-release240.json\').read_text())',
              "    from release240 import verify as verify_release\n    release=verify_release(common)\n    EXPECTED=release['release_header_sha256']")
    runtime.write_text(text,encoding='utf-8',newline='\n')
    test=helper/f'susfs-priority-uid-{code}/test.py';text=test.read_text()
    old="    header=(common/'include/linux/susfs.h').read_text()"
    new=("    for key in ('SUSFS_UID_FILTER_MIN_UID','SUSFS_UID_FILTER_MAX_UID','SUSFS_UID_FILTER_UID_NUM','SUSFS_UID_FILTER_BITMAP_LEN'):\n"
         "        match=re.search(r'^#define '+key+r' .*$',defs,re.M)\n"
         "        if match:constants+=match[0]+'\\n'\n"+old)
    test.write_text(once(text,old,new),encoding='utf-8',newline='\n')
    if plan is not None:bind_source_pair(helper,code,plan)
