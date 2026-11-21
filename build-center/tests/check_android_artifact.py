"""Exercise the production Java archive reader against GitHub's ZIP encoding."""
import io
from pathlib import Path
import subprocess
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parents[1]
JBR=Path(r'D:\Android Studio\jbr\bin')

class Unseekable(io.BytesIO):
    def seek(self,*args):raise io.UnsupportedOperation('stream')

def archive(path,entries,stored=False):
    stream=Unseekable() if stored else io.BytesIO()
    with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED) as out:
        for name,data in entries:out.writestr(name,data)
    path.write_bytes(stream.getvalue())

result_root=ROOT/'.test-results'
result_root.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='android-zip-',dir=result_root) as tmp:
    work=Path(tmp)
    assert work.resolve().is_relative_to(result_root.resolve())
    archive(work/'expected.zip',[('anykernel.sh',b'fixture'),('STRICT-KMI.txt',b'fixture'),('Image',b'fixture')])
    payload=(work/'expected.zip').read_bytes()
    archive(work/'stored-descriptor.zip',[('kernel.zip',payload),('kernel.zip.sha256',b'fixture')],True)
    with zipfile.ZipFile(work/'stored-descriptor.zip') as stored:
        assert all(e.compress_type==zipfile.ZIP_STORED and e.flag_bits&8 for e in stored.infolist())
    archive(work/'deflated.zip',[('kernel.zip',payload)])
    archive(work/'multiple.zip',[('a.zip',payload),('b.zip',payload)])
    archive(work/'traversal.zip',[('../kernel.zip',payload)])
    archive(work/'missing.zip',[('readme.txt',b'fixture')])
    archive(work/'large.zip',[('kernel.zip',b'x'*1000)])
    subprocess.run([str(JBR/'javac.exe'),'-encoding','UTF-8','-d',str(work),
                    str(ROOT/'android/src/com/kaoslab/buildcenter/KernelArtifact.java'),
                    str(ROOT/'tests/java/KernelArtifactTest.java')],check=True)
    subprocess.run([str(JBR/'java.exe'),'-cp',str(work),'KernelArtifactTest',str(work)],check=True)
