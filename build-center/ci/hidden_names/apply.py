"""Wire the existing runtime/owner-aware name policy into all readdir ABIs."""
from pathlib import Path
import argparse
import gzip
import hashlib
import json
import re
import subprocess

HERE=Path(__file__).resolve().parent
STATE='.susfs-hidden-name-readdir.json'
REVISION='hidden-name-readdir-v2'
CALLBACKS=('fillonedir','filldir','filldir64','compat_fillonedir','compat_filldir')

def sha(data):return hashlib.sha256(data).hexdigest()

def once(source,old,new,count=1):
    if source.count(old)!=count:raise RuntimeError('Unexpected readdir anchor: '+repr(old))
    return source.replace(old,new)

def transform(source, *, preserve_partial_reads=True):
    source=once(source,'#include <asm/unaligned.h>',
        '#include <asm/unaligned.h>\n\n#ifdef CONFIG_KSU_SUSFS_HIDDEN_NAME\n#include <linux/susfs_name_filter.h>\n#endif')
    source=once(source,'\tstruct dir_context ctx;','\tstruct dir_context ctx;\n#ifdef CONFIG_KSU_SUSFS_HIDDEN_NAME\n\tbool hidden_name_scope;\n#endif',5)
    source=once(source,'#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n\tbuf.sb = f.file->f_inode->i_sb;',
        '#ifdef CONFIG_KSU_SUSFS_HIDDEN_NAME\n\tbuf.hidden_name_scope = susfs_hidden_name_dir(f.file);\n#endif\n\n#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n\tbuf.sb = f.file->f_inode->i_sb;',5)
    for name in CALLBACKS:
        start=source.index('static bool '+name+'(');end=source.index('\n}',start)+2
        body=source[start:end]
        member='result' if name in ('fillonedir','compat_fillonedir') else 'error'
        anchor='\tbuf->'+member+' = verify_dirent_name(name, namlen);\n\tif ('+('buf->result' if member=='result' else 'unlikely(buf->error)')+')\n\t\treturn false;'
        if member=='error' and preserve_partial_reads:
            # A hidden trailing entry must not reset buf->error after visible
            # entries were emitted. ZeroMount uses that state before normal
            # partial-buffer finalization. Keep validation errors separate.
            opening=body.index('{\n')+2
            body=body[:opening]+'\tint hidden_name_error;\n'+body[opening:]
            validation='\thidden_name_error = verify_dirent_name(name, namlen);\n\tif (unlikely(hidden_name_error)) {\n\t\tbuf->error = hidden_name_error;\n\t\treturn false;\n\t}'
            body=once(body,anchor,validation)
            anchor=validation
        block='\n#ifdef CONFIG_KSU_SUSFS_HIDDEN_NAME\n\tif (buf->hidden_name_scope &&\n\t    susfs_is_hidden_name(name, namlen, current_uid().val))\n\t\treturn true; /* Skip without consuming userspace buffer space. */\n#endif'
        body=once(body,anchor,anchor+block)
        source=source[:start]+body+source[end:]
    return source

def original(source):
    source=source.replace('\n\n#ifdef CONFIG_KSU_SUSFS_HIDDEN_NAME\n#include <linux/susfs_name_filter.h>\n#endif','',1)
    source=source.replace('\n#ifdef CONFIG_KSU_SUSFS_HIDDEN_NAME\n\tbool hidden_name_scope;\n#endif','')
    source=source.replace('#ifdef CONFIG_KSU_SUSFS_HIDDEN_NAME\n\tbuf.hidden_name_scope = susfs_hidden_name_dir(f.file);\n#endif\n\n','')
    source=source.replace('\tint hidden_name_error;\n','')
    source=source.replace('\thidden_name_error = verify_dirent_name(name, namlen);\n\tif (unlikely(hidden_name_error)) {\n\t\tbuf->error = hidden_name_error;\n\t\treturn false;\n\t}',
        '\tbuf->error = verify_dirent_name(name, namlen);\n\tif (unlikely(buf->error))\n\t\treturn false;')
    block='\n#ifdef CONFIG_KSU_SUSFS_HIDDEN_NAME\n\tif (buf->hidden_name_scope &&\n\t    susfs_is_hidden_name(name, namlen, current_uid().val))\n\t\treturn true; /* Skip without consuming userspace buffer space. */\n#endif'
    return source.replace(block,'')

def verify(common):
    data=json.loads((common/STATE).read_text())
    for path,expected in data['output_sha256'].items():
        if sha((common/path).read_bytes())!=expected:raise RuntimeError('Hidden-name source drift: '+path)
    if data['revision']!=REVISION:raise RuntimeError('Wrong hidden-name revision')
    text=(common/'fs/readdir.c').read_text()
    if transform(original(text))!=text:raise RuntimeError('Incomplete hidden-name callback integration')
    # ZeroMount does not inject names for the umounted app processes to which
    # the existing stat/access policy applies. Do not weaken that guard.
    zm=(common/'fs/zeromount.c').read_text()
    begin=zm.index('void zeromount_inject_dents_common(')
    guard=zm[begin:zm.index('\n\tif (atomic_read(',begin)]
    if not re.search(r'if \(susfs_is_current_proc_umounted\(\)\)\s*return;',guard):
        raise RuntimeError('ZeroMount can bypass the umounted-app directory policy')
    return data

def apply(common):
    if (common/STATE).exists():return verify(common)
    source=(common/'fs/readdir.c').read_text();updated=transform(source)
    header=(HERE/'susfs_name_filter.h').read_bytes()
    for symbol in ('susfs_is_hidden_name','susfs_runtime_enabled(SUSFS_RT_HIDDEN_NAME)'):
        if symbol not in (common/'fs/susfs.c').read_text():raise RuntimeError('Existing runtime name policy missing: '+symbol)
    if not re.search(r'^SUBLEVEL = 162$',(common/'Makefile').read_text(),re.M):raise RuntimeError('Unreviewed kernel baseline')
    # Validate every anchor before changing effective sources.
    files={'fs/readdir.c':updated.encode(),'include/linux/susfs_name_filter.h':header}
    for name,data in files.items():(common/name).write_bytes(data)
    state={'schema':1,'revision':REVISION,'callbacks':list(CALLBACKS),
        'input_sha256':{'fs/readdir.c':sha(source.encode())},
        'output_sha256':{name:sha(data) for name,data in files.items()},
        'policy':'existing runtime-controlled susfs_is_hidden_name with owner exemption; Android/data and Android/obb only',
        'inode_cache_required':False,'partial_read_state_preserved':True,'kernel_abi_changed':False,'device_tested':False}
    (common/STATE).write_text(json.dumps(state,indent=2)+'\n')
    return verify(common)

def attest(common,image,vmlinux,nm):
    state=verify(common);blob=image.read_bytes()
    start=blob.index(b'IKCFG_ST')+8;end=blob.index(b'IKCFG_ED',start);config=gzip.decompress(blob[start:end])
    if b'CONFIG_KSU_SUSFS_HIDDEN_NAME=y' not in config.splitlines():raise RuntimeError('Hidden names not enabled in final Image')
    symbols=subprocess.check_output([nm,'--defined-only',str(vmlinux)],text=True)
    if not re.search(r' [tT] susfs_is_hidden_name(?:\.llvm\.[0-9]+)?$',symbols,re.M):raise RuntimeError('Name policy missing from linked kernel')
    return dict(state,image_sha256=sha(blob),vmlinux_sha256=sha(vmlinux.read_bytes()),
        embedded_config_sha256=sha(config),compiled_symbol='susfs_is_hidden_name',device_tested=False)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--common',type=Path,required=True);p.add_argument('--verify-only',action='store_true');p.add_argument('--image',type=Path);p.add_argument('--vmlinux',type=Path);p.add_argument('--receipt',type=Path);p.add_argument('--nm',default='nm');a=p.parse_args()
    result=verify(a.common) if a.verify_only else apply(a.common)
    if any((a.image,a.vmlinux,a.receipt)):
        if not all((a.image,a.vmlinux,a.receipt)):p.error('Image attestation requires --image --vmlinux --receipt')
        result=attest(a.common,a.image,a.vmlinux,a.nm);a.receipt.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
