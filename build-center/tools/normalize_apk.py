"""Normalize Windows aapt2 asset entry separators before alignment/signing.

Android AssetManager treats a backslash as part of a filename. Some Windows
aapt2 builds write that separator into asset ZIP names. ZipInfo.filename on
Windows hides it; inspect orig_filename and rewrite every entry explicitly.
"""
import copy
import io
from pathlib import Path
import sys
import zipfile

def normalize(path):
    data=path.read_bytes();output=io.BytesIO();changed=0
    with zipfile.ZipFile(io.BytesIO(data)) as source,zipfile.ZipFile(output,'w') as dest:
        for entry in source.infolist():
            info=copy.copy(entry)
            info.filename=entry.orig_filename.replace('\\','/')
            changed+=int(info.filename!=entry.orig_filename)
            dest.writestr(info,source.read(entry))
    path.write_bytes(output.getvalue())
    print(f'APK asset paths normalized: {changed} entries')

if __name__=='__main__':normalize(Path(sys.argv[1]))
