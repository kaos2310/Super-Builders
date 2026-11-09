from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'.test-results/SuSFS-v2.4.0-69b8e734-samsung.zip'
raw=p.read_bytes();digest=hashlib.sha256(raw).hexdigest()
assert digest=='0b27808718615ad94b6cdacbcd15d8a27b22f3126fee3dd644ab4e72d2fa16bc'
with zipfile.ZipFile(p) as z:
    assert z.testzip() is None
    header=next(n for n in z.namelist() if n.endswith('/kernel_patches/include/linux/susfs.h'))
    assert b'#define SUSFS_VERSION "v2.4.0"' in z.read(header)
result={'app_installed':True,'cold_start_ms':346,'app_own_error_logs':False,
    'live_source_versions':['41168','v2.4.0'],'susfs_archive_bytes':len(raw),
    'susfs_archive_sha256':digest,'susfs_zip_crc_passed':True,
    'kernel_flash_executed':False,'github_build_started':False}
(ROOT/'.test-results/android-samsung-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
