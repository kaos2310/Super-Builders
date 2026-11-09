from pathlib import Path
import io
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from center_core import request,sha256

url='https://github.com/rhysd/actionlint/releases/download/v1.7.12/actionlint_1.7.12_windows_amd64.zip'
raw=request(url,binary=True)
if sha256(raw)!='6e7241b51e6817ea6a047693d8e6fed13b31819c9a0dd6c5a726e1592d22f6e9':
    raise RuntimeError('Official actionlint release digest mismatch')
dest=Path(__file__).resolve().parents[1]/'.build-deps/actionlint.exe'
with zipfile.ZipFile(io.BytesIO(raw)) as z:dest.write_bytes(z.read('actionlint.exe'))
print('actionlint v1.7.12 downloaded and SHA-256 verified')
