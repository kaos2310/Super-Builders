"""Smoke-test the packaged executable and close its own process tree."""
from pathlib import Path
import json
import subprocess
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
VERSION=json.loads((ROOT/'config.json').read_text())['version']
p=subprocess.Popen([str(ROOT/f'dist/{VERSION}/SukiSU-Build-Center-{VERSION}.exe'),'--no-browser','--stay','--port','18944'],
                   creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
try:
    for _ in range(80):
        try:
            with urllib.request.urlopen('http://127.0.0.1:18944/api/info',timeout=2) as r:info=json.load(r)
            break
        except Exception:time.sleep(.15)
    else:raise RuntimeError('Packaged EXE did not start')
    assert info=={'app':'SukiSU Build Center','mode':'windows','version':VERSION}
    with urllib.request.urlopen('http://127.0.0.1:18944/') as r:html=r.read().decode()
    assert 'SHA-256-Prüfsummen' in html and 'GitHub-Verbindung' in html
    result={'packaged_exe_started':True,'embedded_final_ui_served':True,'info':info}
    (ROOT/'.test-results/windows-runtime.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
finally:
    # This PID was created above exclusively for this test, including the
    # PyInstaller one-file child. Do not leave a locked executable behind.
    subprocess.run(['taskkill.exe','/PID',str(p.pid),'/T','/F'],capture_output=True)
    try:p.wait(timeout=15)
    except subprocess.TimeoutExpired:p.terminate()
