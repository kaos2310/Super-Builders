from pathlib import Path
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ci import runtime


class SusfsMergeTests(unittest.TestCase):
    def test_endif_annotation_does_not_conflict_with_adjacent_feature(self):
        base=b'#ifdef CONFIG_KSU_SUSFS_SUS_PATH\nextern bool hidden(void);\n#endif\nnext();\n'
        local=base.replace(b'next();',b'#ifdef CONFIG_ZEROMOUNT\nextern int mount_hook(void);\n#endif\nnext();')
        target=base.replace(b'extern bool',b'extern __attribute__((hot)) bool').replace(b'#endif\n',b'#endif // #ifdef CONFIG_KSU_SUSFS_SUS_PATH\n')
        merged=runtime.three_way(local,base,target)
        self.assertIn(b'__attribute__((hot))',merged)
        self.assertIn(b'extern int mount_hook(void);',merged)
        self.assertEqual(len(re.findall(rb'^#ifdef',merged,re.M)),2)
        self.assertEqual(merged.count(b'#endif'),2)
        self.assertIn(b'#endif // #ifdef CONFIG_KSU_SUSFS_SUS_PATH\n',merged)

    def test_nested_scope_markers_are_restored_for_logging_helpers(self):
        raw=b'#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG\n#if OTHER\ncall();\n#endif\n#endif\n'
        actual=runtime.restore_endif_annotations(raw)
        self.assertEqual(actual,b'#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG\n#if OTHER\ncall();\n#endif\n#endif // #ifdef CONFIG_KSU_SUSFS_ENABLE_LOG\n')
        with self.assertRaisesRegex(RuntimeError,'Unclosed'):runtime.restore_endif_annotations(b'#ifdef CONFIG_KSU_SUSFS\n')

    def test_normalization_is_limited_to_directive_annotations(self):
        original=b'const char *s = "#endif // #ifdef CONFIG_KSU_SUSFS";\n#endif // Other comment\n#endif // #ifdef CONFIG_OTHER\n'
        self.assertEqual(runtime.without_endif_annotations(original),original)

    def test_actual_c_conflict_still_fails(self):
        with self.assertRaises(runtime.SusfsMergeConflict) as caught:
            runtime.three_way(b'int value = 2;\n',b'int value = 1;\n',b'int value = 3;\n')
        self.assertIn(b'<<<<<<<',caught.exception.output)

    def test_no_partial_write_and_exact_conflict_evidence(self):
        with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stdout(io.StringIO()):
            root=Path(tmp);common=root/'common';common.mkdir();work=root/'.build-center-susfs';work.mkdir()
            (common/'a.c').write_bytes(b'int a=2;\n');(common/'b.c').write_bytes(b'int b=1;\n')
            (work/'base-a').write_bytes(b'int a=1;\n');(work/'target-a').write_bytes(b'int a=3;\n')
            (work/'base-b').write_bytes(b'int b=1;\n');(work/'target-b').write_bytes(b'int b=4;\n')
            (work/'delta.json').write_text(json.dumps({'a.c':{'base':'base-a','target':'target-a'},'b.c':{'base':'base-b','target':'target-b'}}))
            (work/'upstream-changes.json').write_text('{}')
            with patch.object(runtime,'context',return_value=(root,{})):
                with self.assertRaisesRegex(RuntimeError,'a.c'):runtime.sync_susfs(common,root/'ksu')
            self.assertEqual((common/'a.c').read_bytes(),b'int a=2;\n')
            self.assertEqual((common/'b.c').read_bytes(),b'int b=1;\n')
            record=json.loads((work/'upstream-changes.json').read_text())['merge_conflicts'][0]
            self.assertEqual(record['path'],'a.c')
            self.assertEqual(record['local'],'int a=2;\n')
            self.assertEqual(record['target'],'int a=3;\n')


if __name__=='__main__':unittest.main()
