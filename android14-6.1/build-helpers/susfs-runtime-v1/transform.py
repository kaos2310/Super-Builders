#!/usr/bin/env python3
"""Generate an isolated patch for the inspected SukiSU 41159 / SUSFS 2.3 tree."""
import argparse, difflib, hashlib, json, subprocess
from pathlib import Path
HERE = Path(__file__).resolve().parent
PIN = 'fae5788d2984e0c5844e8af96a18c569225d9774'

def once(source, old, new):
    if source.count(old) != 1: raise RuntimeError('Source drift at ' + repr(old))
    return source.replace(old, new, 1)

def transform(original):
    result = dict(original)
    path = 'common/fs/susfs.c'
    result[path] = once(result[path], 'extern bool susfs_is_current_ksu_domain(void);',
        'extern bool susfs_is_current_ksu_domain(void);\n#include "susfs_runtime_impl.h"')
    for name, bit in [('susfs_check_unicode_bypass','SUSFS_RT_UNICODE'), ('susfs_is_hidden_name','SUSFS_RT_HIDDEN_NAME'), ('susfs_is_hidden_ino','SUSFS_RT_HIDDEN_NAME')]:
        start = result[path].index('bool ' + name + '(')
        end = result[path].index('\n}', start) + 2
        body = result[path][start:end]
        body = once(body, '\tif (!susfs_uid_gate_current())', '\tif (!susfs_runtime_enabled(' + bit + ') || !susfs_uid_gate_current())')
        result[path] = result[path][:start] + body + result[path][end:]
    path = 'common/include/linux/susfs_uid_gate.h'
    result[path] = once(result[path], '#include <linux/cred.h>', '#include <linux/cred.h>\n#include <linux/susfs_runtime.h>')
    result[path] = once(result[path], '\treturn uid != (unsigned int)-1',
        '\tif (!susfs_runtime_enabled(SUSFS_RT_UID_GATE))\n\t\treturn true; /* Legacy ungated consumers; does not change root authorization. */\n\treturn uid != (unsigned int)-1')
    path = 'common/kernel/kallsyms.c'
    result[path] = once(result[path], '#include <linux/kallsyms.h>',
        '#include <linux/kallsyms.h>\n#include <linux/susfs_runtime.h>')
    result[path] = once(result[path], 'if (susfs_starts_with(iter->name, "ksu_") ||',
        'if (susfs_runtime_enabled(SUSFS_RT_SYMBOLS) &&\n\t\t    (susfs_starts_with(iter->name, "ksu_") ||')
    result[path] = once(result[path], 'susfs_starts_with(iter->name, "is_zygote"))', 'susfs_starts_with(iter->name, "is_zygote")))')
    path = 'candidate/kernel/supercall/dispatch.c'
    result[path] = once(result[path], '#include <linux/susfs.h>', '#include <linux/susfs.h>\n#include <linux/susfs_runtime.h>')
    result[path] = once(result[path], 'int ksu_handle_susfs_cmd(unsigned int cmd, void __user **arg)\n{\n    switch (cmd) {',
        'int ksu_handle_susfs_cmd(unsigned int cmd, void __user **arg)\n{\n    switch (cmd) {\n    case CMD_SUSFS_RUNTIME_GET:\n    case CMD_SUSFS_RUNTIME_SET:\n        return susfs_runtime_handle(cmd, *arg);')
    for name in ['susfs_runtime.h', 'susfs_runtime_abi.h']:
        result['common/include/linux/' + name] = (HERE / name).read_text()
    result['common/fs/susfs_runtime_impl.h'] = (HERE / 'susfs_runtime.inc').read_text()
    return result

def prepare(lab, output):
    pin = subprocess.check_output(['git','-C',str(lab/'candidate'),'rev-parse','HEAD'], text=True).strip()
    if pin != PIN: raise RuntimeError('Expected SukiSU 41159 source pin')
    paths = ['common/fs/susfs.c','common/include/linux/susfs_uid_gate.h','common/kernel/kallsyms.c','candidate/kernel/supercall/dispatch.c']
    original = {name:(lab/name).read_text() for name in paths}
    if '#define SUSFS_VERSION "v2.3.0"' not in (lab/'common/include/linux/susfs.h').read_text(): raise RuntimeError('Wrong SUSFS version')
    result = transform(original)  # ALL anchors checked before any output.
    if output.exists(): raise RuntimeError('Output already exists; use a new isolated output directory')
    patch = []
    for name, text in result.items():
        file = output/name; file.parent.mkdir(parents=True,exist_ok=True); file.write_text(text)
        patch += difflib.unified_diff(original.get(name,'').splitlines(True),text.splitlines(True),fromfile='a/'+name if name in original else '/dev/null',tofile='b/'+name)
    (output/'susfs-runtime-v1.patch').write_text(''.join(patch))
    manifest = {'sukisu_pin':pin,'susfs_version':'v2.3.0','input_sha256':{n:hashlib.sha256(t.encode()).hexdigest() for n,t in original.items()},
        'output_sha256':{n:hashlib.sha256(t.encode()).hexdigest() for n,t in result.items()},'source_trees_modified':False,'kernel_flashed':False}
    (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--lab',type=Path,required=True); p.add_argument('--output',type=Path,required=True); a=p.parse_args()
    print(json.dumps(prepare(a.lab,a.output),indent=2))
