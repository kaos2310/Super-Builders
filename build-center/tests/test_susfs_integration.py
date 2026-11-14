from pathlib import Path
import hashlib
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ci import release_identity,runtime,susfs_helpers
from ci.generate_workflows import Loader


class ReleaseIdentityTests(unittest.TestCase):
    def test_fresh_merged_header_is_bound_to_plan_and_immutable_source_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);common=root/'common';(common/'include/linux').mkdir(parents=True)
            header=b'#define SUSFS_VERSION "v2.4.0"\nstruct new_upstream_type { int value; };\n'
            (common/'include/linux/susfs.h').write_bytes(header)
            plan={'profile':'S928BXXS6EZJ1-EUX-android14-6.1.162','susfs_version':'v2.4.0',
                  'susfs_commit':'a'*40,'susfs_release_base':'b'*40,'susfs_functional_base':'c'*40}
            (root/'.build-center-plan.json').write_text(json.dumps(plan))
            update={'source_pin':'a'*40,'release_base':'b'*40,'susfs_version':'v2.4.0','conflicts':0,
                    'effective_source_sha256':{'include/linux/susfs.h':hashlib.sha256(header).hexdigest()}}
            (common/'.build-center-susfs-update.json').write_text(json.dumps(update))
            result=release_identity.apply(common)
            self.assertEqual(result['upstream_release_pin'],'a'*40)
            self.assertFalse(result['release_only_change'])
            self.assertEqual(release_identity.verify(common),result)
            (common/'include/linux/susfs.h').write_bytes(header+b'// drift\n')
            with self.assertRaisesRegex(RuntimeError,'header drift'):release_identity.verify(common)
            (common/'include/linux/susfs.h').write_bytes(header);update['source_pin']='d'*40
            (common/'.build-center-susfs-update.json').write_text(json.dumps(update))
            with self.assertRaisesRegex(RuntimeError,'binding'):release_identity.verify(common)

    def test_unreviewed_helper_is_rejected_before_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper=Path(tmp);file=helper/'susfs-runtime-41183/release240.py';file.parent.mkdir();file.write_text('unreviewed')
            with self.assertRaisesRegex(RuntimeError,'helper changed'):susfs_helpers.prepare(helper,41183)
            self.assertEqual(file.read_text(),'unreviewed')


class SuspathWiringTests(unittest.TestCase):
    def test_control_wiring_is_conditional_idempotent_and_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);common=root/'common';ksu=root/'ksu'
            (common/'include/linux').mkdir(parents=True);(common/'fs').mkdir()
            (ksu/'kernel/supercall').mkdir(parents=True);(ksu/'kernel/manager').mkdir()
            (common/'include/linux/susfs_def.h').write_text('#define CMD_SUSFS_SET_SUS_PATH_UID_FILTER 0x55554\n')
            (common/'fs/susfs.c').write_text('void susfs_set_sus_path_uid_filter(void **p) {}\nvoid susfs_parse_sus_path_app_strings(void) {}\nbool susfs_is_uid_allowed_for_sus_path(uid_t uid) {return false;}\n')
            dispatch=ksu/'kernel/supercall/dispatch.c';dispatch.write_text('#ifdef CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER\n    case CMD_SUSFS_SET_PRIORITY_UID_FILTER: { return 0; }\n#endif\n')
            (ksu/'kernel/manager/pkg_observer.c').write_text('#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs.h>\n#endif\n#ifdef CONFIG_KSU_SUSFS_PRIORITY_UID_FILTER\n    /* Resolve after throne tracking, outside fsnotify locks. */\n    susfs_parse_priority_app_strings();\n#endif\n')
            with patch.object(runtime,'context',return_value=(root,{'susfs_commit':'a'*40,'sukisu_commit':'b'*40})):
                result=runtime.wire_suspath(common,ksu)
                self.assertEqual(runtime.wire_suspath(common,ksu,True),result)
                self.assertEqual(runtime.wire_suspath(common,ksu),result)
                self.assertEqual(dispatch.read_text().count('case CMD_SUSFS_SET_SUS_PATH_UID_FILTER:'),1)
                dispatch.write_text(dispatch.read_text().replace('susfs_set_sus_path_uid_filter(arg);','other(arg);'))
                with self.assertRaisesRegex(RuntimeError,'wiring drift'):runtime.wire_suspath(common,ksu,True)

    def test_source_update_precedes_controls_and_real_final_source_tests(self):
        workflow=yaml.load((ROOT.parent/'.github/workflows/build-center.yml').read_text(encoding='utf-8'),Loader=Loader)
        steps=workflow['jobs']['strict']['steps'];names=[s.get('name','') for s in steps]
        early=names.index('Integrate pinned SuSFS updates before control overlays')
        uid=names.index('Apply UID-gated SUSFS visibility consumers')
        tests=next(i for i,n in enumerate(names) if n.startswith('Test SukiSU '))
        late=names.index('Integrate SuSFS updates and tested hidden-name directory filtering')
        build=names.index('Build Kernel')
        self.assertLess(early,uid);self.assertLess(uid,tests);self.assertLess(tests,late);self.assertLess(late,build)
        self.assertIn('susfs-wire',steps[early]['run'])
        self.assertNotIn('susfs-after',steps[late]['run'])
        self.assertIn('_center_suspath_test.py',steps[late]['run'])


if __name__=='__main__':unittest.main()
