#!/usr/bin/env python3
"""Offline regression checks for the partial Android 17 source provider graph."""
import ast
import contextlib
import io
import os
from pathlib import Path
import re
import shutil
import tempfile
import textwrap
import unittest
from unittest.mock import patch
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (ROOT / "scripts/patch-crosvm-gunyah-irqfd.py").read_text(encoding="utf-8")
WORKFLOW = (ROOT / ".github/workflows/build-crosvm-avf-irq16.yml").read_text(encoding="utf-8")
BLOCKS = [textwrap.dedent(block) for block in re.findall(
    r"python3 - <<'PY'[^\n]*\n(.*?)^          PY$", WORKFLOW, re.M | re.S
)]
SELECTOR = next(block for block in BLOCKS if "prefixes =" in block)
PRUNER = next(block for block in BLOCKS if "root_keep =" in block)
PREFIXES = next(ast.literal_eval(node.value) for node in ast.parse(SELECTOR).body
                if isinstance(node, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == "prefixes"
                    for target in node.targets))

# Import pure helpers without running the build wrapper's repo sync/patch chain.
functions = [node for node in ast.parse(WRAPPER).body if isinstance(node, ast.FunctionDef)]
HELPERS = {"Path": Path, "re": re}
exec(compile(ast.Module(body=functions, type_ignores=[]), "wrapper-functions", "exec"), HELPERS)


@contextlib.contextmanager
def fixture_directory():
    # Inherit parent permissions: Windows sandbox tokens cannot traverse the
    # user-only ACL imposed by Python's mode-0700 TemporaryDirectory creation.
    parent = Path(tempfile.gettempdir()).resolve()
    fixture = parent / ("crosvm-a17-preflight-" + uuid.uuid4().hex)
    fixture.mkdir()
    try:
        yield fixture
    finally:
        if fixture.resolve().parent != parent:
            raise RuntimeError(f"unsafe fixture cleanup target: {fixture}")
        shutil.rmtree(fixture)


class Android17PreflightTests(unittest.TestCase):
    def test_ndk_alias_uses_v2_not_highest_allocator_snapshot(self):
        # A17 graphics/Android.bp has no allocator-latest or allocator-ndk_static.
        # Its shared alias is V2 despite the allocator API also having frozen V3.
        aliases = '\n'.join((
            'name: "android.hardware.graphics.allocator-ndk_shared",',
            'shared_libs: ["android.hardware.graphics.allocator-V2-ndk"],',
            'imports: ["android.hardware.graphics.common-V7"],',
            'static_libs: ["android.hardware.graphics.common-V7-ndk"],',
            'shared_libs: ["android.hardware.graphics.common-V7-ndk"],',
        ))
        self.assertEqual(HELPERS["graphics_aidl_versions"](aliases), (2, 7))

    def test_missing_or_ambiguous_ndk_alias_fails_closed(self):
        for allocator in ('"android.hardware.graphics.allocator-V2"',
                          '"android.hardware.graphics.allocator-V2-ndk" '
                          '"android.hardware.graphics.allocator-V3-ndk"'):
            with self.subTest(allocator=allocator), self.assertRaises(SystemExit):
                HELPERS["graphics_aidl_versions"](
                    allocator + ' "android.hardware.graphics.common-V7-ndk"')

    def run_selector(self, prefixes):
        manifest = ET.Element("manifest")
        for prefix in prefixes:
            path = prefix.rstrip("/")
            if path == "external/rust":
                path += "/crates/test"
            ET.SubElement(manifest, "project", path=path, name="platform/" + path)
        with patch.object(ET, "parse", return_value=ET.ElementTree(manifest)):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                exec(compile(SELECTOR, "workflow-selector", "exec"), {})
        return output.getvalue()

    def test_selector_has_no_removed_android17_projects(self):
        for removed in ("system/cros-codecs", "external/libepoxy", "external/gfxstream-protocols"):
            self.assertNotIn(removed, PREFIXES)
        self.assertIn("platform/external/crosvm", self.run_selector(PREFIXES))

    def test_removed_required_project_fails_before_sync(self):
        with self.assertRaisesRegex(SystemExit, "external/crosvm"):
            self.run_selector([p for p in PREFIXES if p != "external/crosvm"])

    def test_siso_bootstrap_provider_is_selected_and_checked(self):
        self.assertIn("prebuilts/siso", PREFIXES)
        self.assertIn("platform/prebuilts/siso", self.run_selector(PREFIXES).splitlines())
        self.assertIn("grep -q '^platform/prebuilts/siso$' /tmp/crosvm-projects.txt", WORKFLOW)
        self.assertIn("test -x prebuilts/siso/linux-x86/siso", WORKFLOW)
        self.assertIn("test -f build/soong/siso_config/main.star", WORKFLOW)
        for module in ("clang", "java", "rust"):
            self.assertIn(f"test -f build/soong/siso_config/{module}.star", WORKFLOW)
        version_check = WORKFLOW.index("prebuilts/siso/linux-x86/siso version -online=false")
        self.assertLess(WORKFLOW.index("repo sync -c"), version_check)
        self.assertLess(version_check, WORKFLOW.index("- name: Verify exact crosvm source revision"))

    def test_missing_siso_project_fails_before_sync(self):
        with self.assertRaisesRegex(SystemExit, "prebuilts/siso"):
            self.run_selector([p for p in PREFIXES if p != "prebuilts/siso"])

    def test_siso_output_is_relative_and_inside_source_root(self):
        self.assertRegex(WORKFLOW, r"(?m)^      OUT_DIR: out$")
        self.assertNotIn("/opt/aosp-build/out", WORKFLOW)
        init = WORKFLOW.split("- name: Initialize Android 17 r1 manifest", 1)[1].split("- name:", 1)[0]
        self.assertIn('test "$OUT_DIR" = out', init)
        self.assertLess(init.index('cd "$AOSP_DIR"'), init.index('mkdir -p "$OUT_DIR"'))

    def test_output_consumers_use_the_same_source_working_directory(self):
        blocks = re.findall(r"^        run: \|\n(.*?)(?=^      - name:|\Z)", WORKFLOW, re.M | re.S)
        consumers = 0
        for block in blocks:
            # The initial literal-value guard does not access the filesystem.
            block = block.replace('test "$OUT_DIR" = out', '')
            if "$OUT_DIR" not in block:
                continue
            consumers += 1
            self.assertIn('cd "$AOSP_DIR"', block)
            self.assertLess(block.index('cd "$AOSP_DIR"'), block.index('$OUT_DIR'))
        self.assertEqual(consumers, 4)  # init, source preflight, build, collection

    def test_release_uses_stable_android17_with_fail_closed_identity(self):
        self.assertRegex(WORKFLOW, r"(?m)^      AOSP_RELEASE: cp2a$")
        self.assertIn('lunch module_arm64 "$AOSP_RELEASE" eng', WORKFLOW)
        self.assertNotIn('lunch module_arm64 trunk_staging eng', WORKFLOW)
        for guard in ('test "$TARGET_RELEASE" = cp2a',
                      'test "$(get_build_var OUT_DIR)" = out',
                      'test "$PLATFORM_VER" = 17',
                      'test "$PLATFORM_CODENAME" = REL',
                      'test "$PLATFORM_SDK" = 37'):
            self.assertLess(WORKFLOW.index(guard), WORKFLOW.index('m -j2 -k0 crosvm'))
        self.assertIn('cp "$OUT_DIR/platform-build-identity.txt" "$DEST/"', WORKFLOW)
        self.assertIn('TARGET=module_arm64-$AOSP_RELEASE-eng', WORKFLOW)

    def test_version_providers_are_pinned_before_patching(self):
        for path, revision in (
            ("make", "5ce6f787337d0223710bf7d4a16dbe6d2a35f777"),
            ("release", "c85f4aebe46714235599a9bd6430a0fe30c6e8d5"),
            ("soong", "6722dd8833db7482df1a2543ca3fcf67ddf0f7b1"),
        ):
            guard = f'test "$(git -C build/{path} rev-parse HEAD)" = "{revision}"'
            self.assertLess(WORKFLOW.index(guard), WORKFLOW.index('- name: Apply Samsung'))

    def test_pruner_keeps_drm_common_but_not_drm_hal(self):
        with fixture_directory() as temporary:
            root = Path(temporary) / "hardware/interfaces"
            for path in ("graphics", "common", "drm/common/aidl", "drm/aidl",
                         "drm/1.0", "media/1.0", "media/c2", "audio"):
                (root / path).mkdir(parents=True)
            previous = Path.cwd()
            try:
                os.chdir(temporary)
                exec(compile(PRUNER, "workflow-pruner", "exec"), {})
            finally:
                os.chdir(previous)
            for kept in ("graphics", "common", "drm/common/aidl", "media/1.0"):
                self.assertTrue((root / kept).is_dir(), kept)
            for removed in ("drm/aidl", "drm/1.0", "media/c2", "audio"):
                self.assertFalse((root / removed).exists(), removed)

    def test_display_provider_links_native_handle_implementation(self):
        prepare = ast.parse((ROOT / "scripts/prepare-crosvm-binder-deps.py").read_text(encoding="utf-8"))
        generated = next(node.value for node in ast.walk(prepare)
                         if isinstance(node, ast.Constant) and isinstance(node.value, str)
                         and 'cc_library_static {' in node.value
                         and 'name: "libcrosvm_android_display_client"' in node.value)
        self.assertRegex(generated, r'shared_libs:\s*\[[^]]*"libcutils"')

    def test_team_metadata_refresh_follows_late_provider_sync(self):
        self.assertLess(WRAPPER.index('runpy.run_path(str(CORE)'), WRAPPER.index('refs, defs ='))


if __name__ == "__main__":
    unittest.main(verbosity=2)
