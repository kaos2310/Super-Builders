#!/usr/bin/env python3
"""Regression tests for Cargo-reported ksud bindings paths and UAPI5 rejection."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
import resukisu_35203_uapi as audit


class BindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        # Deliberately outside every assumed Cargo release/build layout.
        self.out = self.root / 'intermediates/custom-cargo-layout/ksud-generated'
        self.out.mkdir(parents=True)
        self.bindings = self.out / 'bindings.rs'
        self.valid = ('pub const KERNEL_SU_UAPI_VERSION: __u32 = 5;\n'
                      'pub const EVENT_SERVICES: _bindgen_ty_4 = 4;\n')
        self.bindings.write_text(self.valid, encoding='utf-8')
        self.messages_path = self.root / 'ksud-build-messages.jsonl'
        self.package = 'path+file:///checkout/userspace/ksud#0.1.0'
        self.messages = [
            dict(reason='compiler-artifact', package_id=self.package,
                 manifest_path=str(self.root / 'userspace/ksud/Cargo.toml'),
                 target=dict(kind=['custom-build']), fresh=False),
            dict(reason='build-script-executed', package_id=self.package, out_dir=str(self.out)),
            dict(reason='build-finished', success=True),
        ]

    def verify(self):
        self.messages_path.write_text('\n'.join(json.dumps(m) for m in self.messages) + '\n', encoding='utf-8')
        return audit.verify_bindings(self.root, self.messages_path)

    def test_uses_reported_out_dir_without_assuming_layout(self):
        result = self.verify()
        self.assertEqual(result['path'], str(self.bindings))
        self.assertEqual(result['package_id'], self.package)
        self.assertEqual(result['uapi_version'], 5)

    def test_ignores_stale_bindings_in_the_old_assumed_directory(self):
        stale = self.root / 'userspace/ksud/target/aarch64-linux-android/release/build/ksud-stale/out/bindings.rs'
        stale.parent.mkdir(parents=True)
        stale.write_text(self.valid.replace('= 5;', '= 4;'), encoding='utf-8')
        self.assertEqual(self.verify()['path'], str(self.bindings))

    def test_does_not_substitute_unreported_valid_bindings(self):
        other = self.out.parent / 'unreported/bindings.rs'
        other.parent.mkdir()
        other.write_text(self.valid, encoding='utf-8')
        self.bindings.write_text(self.valid.replace('= 5;', '= 4;'), encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'KERNEL_SU_UAPI_VERSION=5'):
            self.verify()

    def test_rejects_missing_or_wrong_service_constant(self):
        for text in (self.valid.splitlines()[0], self.valid.replace('= 4;', '= 3;')):
            self.bindings.write_text(text, encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'EVENT_SERVICES=4'):
                self.verify()

    def test_requires_this_build_messages(self):
        with self.assertRaisesRegex(RuntimeError, 'requires messages'):
            audit.verify_bindings(self.root)

    def test_rejects_missing_bindings(self):
        self.bindings.unlink()
        with self.assertRaises(FileNotFoundError):
            self.verify()

    def test_rejects_failed_or_missing_build_completion(self):
        self.messages[-1]['success'] = False
        with self.assertRaisesRegex(RuntimeError, 'successful ksud build'):
            self.verify()
        self.messages.pop()
        with self.assertRaisesRegex(RuntimeError, 'successful ksud build'):
            self.verify()

    def test_rejects_dependency_build_script(self):
        self.messages[0]['manifest_path'] = str(self.root / 'dependency/Cargo.toml')
        with self.assertRaisesRegex(RuntimeError, 'local ksud build script'):
            self.verify()

    def test_rejects_missing_or_ambiguous_ksud_out_dir(self):
        original = self.messages[1]
        self.messages[1] = dict(reason='build-script-executed', package_id='another-package', out_dir=str(self.out))
        with self.assertRaisesRegex(RuntimeError, 'exactly one ksud OUT_DIR'):
            self.verify()
        self.messages[1] = original
        self.messages.insert(2, dict(original, out_dir=str(self.out.parent)))
        with self.assertRaisesRegex(RuntimeError, 'exactly one ksud OUT_DIR'):
            self.verify()

    def test_keeps_rendered_rust_errors_visible(self):
        stream = io.StringIO('native tool output\n' + json.dumps(dict(
            reason='compiler-message', message=dict(rendered='error: sample Rust error\n'))) + '\n')
        output = io.StringIO()
        with patch.object(sys, 'stdin', stream), patch.object(sys, 'stdout', output):
            audit.render_cargo()
        self.assertEqual(output.getvalue(), 'native tool output\nerror: sample Rust error\n')


if __name__ == '__main__':
    unittest.main()
