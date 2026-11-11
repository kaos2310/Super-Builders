import base64
from datetime import datetime, timezone
import copy
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from center_core import CenterError, SafeRedirect, allowed_url, checked_file, resolve_sources, sha256
from desktop import CenterServer
from ci.bootstrap import prepare, validate
from ci.check_updates import recent_failure
from ci.runtime import three_way
from ci.firmware_profile import DATA as FIRMWARE_DATA
from tools.normalize_apk import normalize


def zip_bytes(items):
    b=io.BytesIO()
    with zipfile.ZipFile(b,'w') as z:
        for name,raw in items:z.writestr(name,raw)
    return b.getvalue()


def valid_kernel(firmware='S928BXXS6EZJ1', image=b'ARM64 kernel', digest=None):
    receipt={'firmware':firmware,'csc':'EUX','profile':'S928BXXS6EZJ1-EUX-android14-6.1.162',
             'image_sha256': digest or sha256(image)}
    return zip_bytes([('anykernel.sh',b'#!/bin/sh'),('Image',image),('STRICT-KMI.txt',b'full-strict'),
                      ('FIRMWARE-TARGET.json',json.dumps(receipt).encode())])


class DownloadTests(unittest.TestCase):
    def test_release_kernel_must_identify_ezj1_and_its_actual_image(self):
        good=valid_kernel()
        self.assertEqual(checked_file(good,'kernel.zip',sha256(good),'kernel')[0],good)
        for bad in (valid_kernel(firmware='S928BXXU6EZIF'), valid_kernel(digest='0'*64)):
            with self.assertRaisesRegex(CenterError,'EZJ1-Firmware'):
                checked_file(bad,'kernel.zip',sha256(bad),'kernel')

    def test_windows_apk_asset_separators_are_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'unsigned.apk'
            with zipfile.ZipFile(p,'w') as z:
                info=zipfile.ZipInfo('assets/web/index.html');info.filename='assets\\web\\index.html'
                z.writestr(info,b'app html')
            normalize(p)
            with zipfile.ZipFile(p) as z:
                self.assertTrue(all('\\' not in i.orig_filename for i in z.infolist()))
                self.assertEqual(z.read('assets/web/index.html'),b'app html')
    def test_outer_digest_then_actual_flash_zip(self):
        kernel=valid_kernel();outer=zip_bytes([('flash/kernel.zip',kernel),('SHA256SUMS',b'receipt')])
        raw,name,digest=checked_file(outer,'artifact.zip','sha256:'+sha256(outer),'kernel-artifact')
        self.assertEqual(raw,kernel);self.assertEqual(name,'kernel.zip');self.assertEqual(digest,sha256(kernel))
    def test_corrupted_download_rejected(self):
        with self.assertRaisesRegex(CenterError,'SHA-256'):checked_file(b'corrupt','kernel.zip','0'*64)
    def test_kernel_digest_required(self):
        with self.assertRaisesRegex(CenterError,'erforderlich'):checked_file(b'x','artifact.zip','','kernel-artifact')
    def test_multiple_flash_zips_rejected(self):
        outer=zip_bytes([('one.zip',valid_kernel()),('two.zip',valid_kernel())])
        with self.assertRaisesRegex(CenterError,'genau eine'):checked_file(outer,'artifact.zip',sha256(outer),'kernel-artifact')
    def test_traversal_entry_rejected(self):
        outer=zip_bytes([('../kernel.zip',valid_kernel())])
        with self.assertRaisesRegex(CenterError,'Unsicherer Pfad'):checked_file(outer,'artifact.zip',sha256(outer),'kernel-artifact')
    def test_non_strict_kernel_rejected(self):
        raw=zip_bytes([('payload.zip',zip_bytes([('anykernel.sh',b'x'),('Image',b'x')]))])
        with self.assertRaisesRegex(CenterError,'Strict-KMI'):checked_file(raw,'artifact.zip',sha256(raw),'kernel-artifact')
    def test_fake_zip_rejected(self):
        raw=b'not a zip'
        with self.assertRaisesRegex(CenterError,'ZIP-Datei'):checked_file(raw,'artifact.zip',sha256(raw),'kernel-artifact')


class NetworkTests(unittest.TestCase):
    def test_expected_hosts_only(self):
        self.assertTrue(allowed_url('https://api.github.com/repos/kaos2310/Super-Builders/actions/runs/123'))
        for url in ('http://api.github.com/repos/a/b','https://api.github.com.evil.test/repos/a/b',
                    'https://user@api.github.com/repos/a/b','https://127.0.0.1:443/repos/a/b','https://api.github.com:8443/repos/a/b'):
            self.assertFalse(allowed_url(url),url)
    def test_write_api_limited_to_dispatch(self):
        self.assertTrue(allowed_url('https://api.github.com/repos/a/b/actions/workflows/build-center.yml/dispatches','POST'))
        self.assertFalse(allowed_url('https://api.github.com/repos/a/b/git/refs','POST'))
        self.assertFalse(allowed_url('https://api.github.com/repos/a/b','DELETE'))
    def test_redirect_strips_authorization(self):
        req=urllib.request.Request('https://api.github.com/repos/a/b/actions/artifacts/1/zip',headers={'Authorization':'Bearer private'})
        moved=SafeRedirect().redirect_request(req,None,302,'Found',{},'https://objects.githubusercontent.com/file')
        self.assertIsNone(moved.get_header('Authorization'))
        with self.assertRaises(CenterError):SafeRedirect().redirect_request(req,None,302,'Found',{},'http://example.test/file')


class ScheduleTests(unittest.TestCase):
    def fake(self,conclusion='failure',created='2026-11-09T12:00:00Z'):
        def get(url,*args):
            data={'artifacts':[{'created_at':created,'expired':False,'workflow_run':{'id':42}}]} if '/artifacts?' in url else {'status':'completed','conclusion':conclusion}
            return {'data':data}
        return get
    def test_same_failed_source_pair_has_a_cooldown(self):
        self.assertTrue(recent_failure('a/b','a-b',get=self.fake(),now=datetime(2026,11,9,13,tzinfo=timezone.utc)))
    def test_success_or_old_failure_does_not_throttle(self):
        now=datetime(2026,11,9,13,tzinfo=timezone.utc)
        self.assertFalse(recent_failure('a/b','a-b',get=self.fake('success'),now=now))
        self.assertFalse(recent_failure('a/b','a-b',get=self.fake(created='2026-11-08T12:00:00Z'),now=now))


class ResolveTests(unittest.TestCase):
    def fake(self,url,token='',**kwargs):
        headers={};pin='a'*40
        if url.endswith('/releases/latest'):data={'tag_name':'v4.3.0-r2','assets':[{'name':'SukiSU_v4.3.0-r2_41150-release.apk'}]}
        elif '/commits?sha=' in url:data=[{'sha':pin}];headers={'link':f'<https://api.github.com/repos/a/b/commits?sha={pin}&per_page=1&page=3983>; rel="last"'}
        elif 'contents/kernel/Kbuild' in url:data={'content':base64.b64encode(b'VERSION_BASE := 40000\nVERSION_OFFSET := 2815\nKSU_VERSION := $(shell expr $(VERSION_BASE) + $(LOCAL_COUNT) - $(VERSION_OFFSET))').decode()}
        elif '/files/' in url:data={'content':base64.b64encode(b'#define SUSFS_VERSION "v2.4.0"').decode()}
        elif 'gitlab.com' in url:data={'id':'b'*40}
        else:data={'sha':pin,'commit':{'message':'manager update\nmore'}}
        return {'data':data,'headers':headers,'status':200}
    def test_current_main_maps_to_41168(self):
        p=resolve_sources(get=self.fake)
        self.assertEqual(p['sukisu_code'],41168);self.assertEqual(p['susfs_version'],'v2.4.0')
        self.assertIsNone(p['manager']);self.assertIn('a'*40,p['sukisu_commit'])
    def test_release_ref_is_resolved_not_assumed_main(self):
        urls=[]
        def get(url,*args,**kw):urls.append(url);return self.fake(url,*args,**kw)
        resolve_sources('release',get=get)
        self.assertTrue(any('/commits/v4.3.0-r2' in url for url in urls))
    def test_missing_count_is_not_reported_as_latest(self):
        def get(url,*args,**kw):
            r=self.fake(url,*args,**kw)
            if '/commits?sha=' in url:r['headers']={}
            return r
        with self.assertRaisesRegex(CenterError,'Commitanzahl'):resolve_sources(get=get)

    def test_explicit_source_pin_is_resolved_with_its_true_count(self):
        urls=[]
        def get(url,*args,**kw):
            urls.append(url);r=self.fake(url,*args,**kw)
            if '/commits?sha=' in url:
                r['headers']['link']=r['headers']['link'].replace('page=3983','page=3993')
            return r
        p=resolve_sources(get=get,source_ref='a'*40)
        self.assertEqual(p['sukisu_code'],41178)
        self.assertEqual(p['sukisu_count'],3993)
        self.assertEqual(p['channel'],'pinned')
        self.assertEqual(p['sukisu_requested_ref'],'a'*40)
        self.assertIn('/commits/'+'a'*40,' '.join(urls))

    def test_explicit_pin_cannot_resolve_to_another_commit(self):
        with self.assertRaisesRegex(CenterError,'Auftrag'):
            resolve_sources(get=self.fake,source_ref='c'*40)

    def test_invalid_explicit_ref_fails_before_any_network_request(self):
        def forbidden(*args,**kwargs):raise AssertionError('Network request was not expected')
        for ref in ('main','refs/pull/1044/merge','a'*39,'a'*41):
            with self.assertRaises(CenterError):resolve_sources(get=forbidden,source_ref=ref)
        with self.assertRaises(CenterError):resolve_sources('release',get=forbidden,source_ref='a'*40)


class MergeTests(unittest.TestCase):
    def test_custom_overlay_and_upstream_change_preserved(self):
        base=b'one\ntwo\nthree\nfour\nfive\nsix\n'
        local=b'custom\none\ntwo\nthree\nfour\nfive\nsix\n'
        target=b'one\ntwo\nthree\nfour\nfive\nupdated\n'
        self.assertEqual(three_way(local,base,target),b'custom\none\ntwo\nthree\nfour\nfive\nupdated\n')
    def test_conflicting_update_fails(self):
        with self.assertRaisesRegex(RuntimeError,'Konflikt'):three_way(b'local\n',b'base\n',b'upstream\n')
    def test_conflicting_delete_fails(self):
        with self.assertRaises(RuntimeError):three_way(b'custom',b'base',None)
    def test_nonconflicting_new_file(self):self.assertEqual(three_way(None,None,b'new'),b'new')


class BootstrapTests(unittest.TestCase):
    def plan(self):
        return {'sukisu_commit':'a'*40,'susfs_commit':'b'*40,'baseline_commit':'c'*40,
            'susfs_release_base':'d'*40,'susfs_functional_base':'e'*40,'sukisu_count':3983,'sukisu_code':41168,
            'susfs_version':'v2.4.0','sukisu_tag':'v4.3.0-r2','profile':'S928BXXS6EZJ1-EUX-android14-6.1.162'}
    def test_invalid_plan_rejected_before_writes(self):
        p=self.plan();p['sukisu_code']=41170
        with self.assertRaisesRegex(ValueError,'mapping'):validate(p)

    def test_reviewed_pin_with_another_valid_formula_fails_before_writes(self):
        p=self.plan();p.update(sukisu_commit='1c9cca42f8049227d4eea20ab3979db3c5662a7d',
                               sukisu_code=41176,sukisu_count=3991)
        with self.assertRaisesRegex(ValueError,'reviewed source/version mapping'):validate(p)
    def test_new_sources_do_not_inherit_compilation_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);h=root/'android14-6.1/build-helpers';port=h/'sukisu-41165-susfs';port.mkdir(parents=True)
            (port/'apply.py').write_text('# old')
            (port/'PREFLIGHT.json').write_text('{"arm64_sukisu_subtree_compiled":true}')
            (h/'configure-sukisu-41165.py').write_text("PIN='d7d042816b82b200c25b3a93dcc158ba0307cabf'\ncount=3980\nversion=41165")
            (root/'.github/workflows').mkdir(parents=True)
            (root/'device-profiles.json').write_text(json.dumps({'devices': {'e3q': {
                'firmware': 'S928BXXU6EZIF', 'stock_kernel': {}, 'firmware_archives':
                {key: {} for key in ('ap', 'bl', 'keep_oem_unlock_bl', 'cp', 'csc', 'home_csc')}
            }}}))
            (root/'android14-6.1/samsung-s928bxxu6ezif-target.env').write_bytes((FIRMWARE_DATA/'baseline-target.env').read_bytes())
            (root/'android14-6.1/samsung-e3q-zzi4-dlkm-crc-baseline.tsv').write_bytes((FIRMWARE_DATA/'strict-baseline.tsv').read_bytes())
            prepare(root,self.plan())
            evidence=json.loads((h/'sukisu-41168-susfs/PREFLIGHT.json').read_text())
            self.assertFalse(evidence['historical_evidence_reused']);self.assertFalse(evidence['full_kernel_link_tested'])
            self.assertNotIn('arm64_sukisu_subtree_compiled',evidence)
            self.assertIn('count=3983',(h/'configure-sukisu-41168.py').read_text())
            self.assertFalse((h/'configure-sukisu-41165.py').exists())


class LocalServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=CenterServer(('127.0.0.1',0));cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.base='http://127.0.0.1:'+str(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close()
    def test_static_app_and_info(self):
        with urllib.request.urlopen(self.base+'/api/info') as r:self.assertEqual(json.load(r)['app'],'SukiSU Build Center')
        with urllib.request.urlopen(self.base+'/') as r:self.assertIn(b'<html lang="de">',r.read())
    def test_cross_origin_mutation_rejected(self):
        req=urllib.request.Request(self.base+'/api/heartbeat',data=b'',headers={'Origin':'https://evil.test','X-Center-Request':'1'})
        with self.assertRaises(urllib.error.HTTPError) as r:urllib.request.urlopen(req)
        self.assertEqual(r.exception.code,403)
    def test_no_custom_header_rejected(self):
        req=urllib.request.Request(self.base+'/api/heartbeat',data=b'')
        with self.assertRaises(urllib.error.HTTPError) as r:urllib.request.urlopen(req)
        self.assertEqual(r.exception.code,403)
    def test_dns_rebinding_host_rejected(self):
        req=urllib.request.Request(self.base+'/api/info',headers={'Host':'evil.test'})
        with self.assertRaises(urllib.error.HTTPError) as r:urllib.request.urlopen(req)
        self.assertEqual(r.exception.code,403)


if __name__=='__main__':unittest.main()
