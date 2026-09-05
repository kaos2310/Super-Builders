#!/usr/bin/env python3
"""Offline regression checks for the partial Android 17 source provider graph."""
import ast
import contextlib
import io
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import textwrap
from types import SimpleNamespace
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
SPEC = importlib.util.spec_from_file_location("crosvm_ci", ROOT / "scripts/crosvm-android17-ci.py")
CI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CI)
NINJA = os.environ.get("CROSVM_TEST_NINJA") or shutil.which("ninja")
RUST_BP = '''
rust_defaults {
    name: "rust_sysroot_defaults",
    apex_available: ["//apex_available:platform", "//apex_available:anyapex"],
    no_stdlibs: true, host_supported: true, vendor_available: true,
    product_available: true, recovery_available: true, sysroot: true,
    edition: "2024",
    target: { glibc: { enabled: false, }, },
}
rust_toolchain_library_rlib { name: "libcore.rust_sysroot", }
rust_toolchain_library_rlib { name: "liballoc.rust_sysroot", }
rust_toolchain_library_rlib { name: "libcompiler_builtins.rust_sysroot", }
cc_defaults { name: "rust_static_cc_lib_defaults", }
'''


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
        self.assertEqual(consumers, 6)  # init, sync, tools, graph, compile, collection

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

    def test_actual_android17_toolchain_paths_are_selected(self):
        selected = self.run_selector(PREFIXES).splitlines()
        for provider in ("prebuilts/rust-toolchain/linux-x86",
                         "prebuilts/rust-toolchain/linux-musl-x86", "prebuilts/clang-tools"):
            self.assertIn(provider, PREFIXES)
            self.assertIn("platform/" + provider, selected)
            with self.subTest(provider=provider), self.assertRaisesRegex(SystemExit, provider):
                self.run_selector([p for p in PREFIXES if p != provider])

    def test_rust_sysroot_contract_preserves_apex_comments_and_nested_blocks(self):
        CI.rust_contract('// comment with { unmatched brace\n' + RUST_BP)

    def test_rust_sysroot_missing_defaults_is_not_masked_by_consumer_apex(self):
        with self.assertRaisesRegex(ValueError, "rust_sysroot_defaults"):
            CI.rust_contract('rust_library_rlib { name: "libbionic_panic_abort", '
                             'apex_available: ["//apex_available:anyapex"], }')

    def test_rust_sysroot_rejects_incomplete_or_duplicate_provider(self):
        for broken in (RUST_BP.replace('"//apex_available:anyapex"', '"com.android.virt"'),
                       RUST_BP.replace("host_supported: true", "host_supported: false"),
                       RUST_BP.replace('edition: "2024"', 'edition: "2021"'),
                       RUST_BP.replace('name: "libcore.rust_sysroot"', 'name: "removed"'),
                       RUST_BP + RUST_BP):
            with self.subTest(broken=broken[:80]), self.assertRaises(ValueError):
                CI.rust_contract(broken)

    def test_toolchain_preflight_collects_multiple_missing_providers(self):
        with fixture_directory() as root, contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError) as error:
                CI.toolchain_check(root)
            message = str(error.exception)
            for item in ("Rust sysroot", "linux-x86 rustc", "linux-musl-x86 rustc",
                         "header-abi-dumper", "header-abi-linker", "header-abi-diff",
                         "libbionic_panic_abort", "liblibc_alloc_rust"):
                self.assertIn(item, message)

    def test_toolchain_preflight_accepts_complete_provider_and_checks_compiler_version(self):
        with fixture_directory() as root:
            def put(relative, text="fixture"):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
                path.chmod(0o755)
            put("build/soong/rust/config/global.go",
                'RustDefaultBase = "prebuilts/rust-toolchain/"\nRustDefaultVersion = "1.93.1"\n')
            for host in ("linux-x86", "linux-musl-x86"):
                put(f"prebuilts/rust-toolchain/{host}/Android.bp", RUST_BP)
                for binary in ("rustc", "rustfmt", "clippy-driver"):
                    put(f"prebuilts/rust-toolchain/{host}/1.93.1/bin/{binary}")
            for crate in ("core", "alloc", "std"):
                put(f"prebuilts/rust-toolchain/linux-x86/1.93.1/lib/rustlib/src/rust/library/{crate}/src/lib.rs")
            for tool in CI.ABI_TOOLS:
                put(f"prebuilts/clang-tools/linux-x86/bin/{tool}")
            put("prebuilts/build-tools/linux-x86/bin/ninja")
            put("system/librustutils/no_std/Android.bp", '\n'.join(
                f'rust_library_rlib {{ name: "{name}", defaults: ["rust_sysroot_defaults"], }}'
                for name in ("libbionic_panic_abort", "liblibc_alloc_rust")))
            with patch.object(CI.subprocess, "check_output", return_value="rustc 1.93.1 (fixture)"), \
                    contextlib.redirect_stdout(io.StringIO()):
                CI.toolchain_check(root)
            with patch.object(CI.subprocess, "check_output", return_value="rustc 1.92.0 (wrong)"), \
                    contextlib.redirect_stdout(io.StringIO()), \
                    self.assertRaisesRegex(ValueError, "unexpected compiler version"):
                CI.toolchain_check(root)

    def test_error_rule_detection(self):
        for command in ('echo "module X missing dependencies: Y" && false',
                        '/bin/echo "other deferred error" && false',
                        '(echo "failure" && false)'):
            self.assertTrue(CI.failing_command(command))
        for command in ('clang -c source.cc -o output.o',
                        'echo false', 'test -f output || false; echo done'):
            self.assertFalse(CI.failing_command(command))

    @unittest.skipUnless(NINJA, "set CROSVM_TEST_NINJA for real Ninja regression fixtures")
    def test_real_ninja_collects_all_reachable_deferred_errors_without_execution(self):
        with fixture_directory() as root:
            graph = root / "build.ninja"
            graph.write_text('rule fail\n  command = echo "module $out missing dependencies: $dep" && false\n'
                             'rule compile\n  command = echo compiled > MUST_NOT_EXIST\n'
                             'build first: fail\n  dep = provider_one\n'
                             'build second: fail\n  dep = provider_two\n'
                             'build validation: fail\n  dep = abi_provider\n'
                             'build unused: fail\n  dep = unrelated\n'
                             'build binary: compile first second |@ validation\n'
                             'build crosvm: phony binary\n')
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                CI.graph_check(root, Path(NINJA), graph, root / "diagnostics")
            report = json.loads((root / "diagnostics/graph-audit.json").read_text())
            self.assertEqual(report["dry_run_exit"], 0)  # dry-run alone falsely passes!
            self.assertEqual(len(report["reachable_error_rules"]), 3)
            self.assertIn("abi_provider", str(report))
            self.assertNotIn("unrelated", str(report))
            self.assertFalse((root / "MUST_NOT_EXIST").exists())

    @unittest.skipUnless(NINJA, "set CROSVM_TEST_NINJA for real Ninja regression fixtures")
    def test_real_ninja_accepts_complete_graph_and_rejects_missing_input(self):
        with fixture_directory() as root:
            graph = root / "build.ninja"
            for dependency in ("", " missing-input.cc"):
                graph.write_text('rule compile\n  command = echo compiled > MUST_NOT_EXIST\n'
                                 f'build binary: compile{dependency}\nbuild crosvm: phony binary\n')
                with contextlib.redirect_stdout(io.StringIO()):
                    if dependency:
                        with self.assertRaises(ValueError):
                            CI.graph_check(root, Path(NINJA), graph, root / "diagnostics")
                    else:
                        CI.graph_check(root, Path(NINJA), graph, root / "diagnostics")
                self.assertFalse((root / "MUST_NOT_EXIST").exists())

    def test_cache_pairs_project_refs_with_shared_objects_and_no_worktrees(self):
        with fixture_directory() as root:
            manifest = root / ".repo/manifests/default.xml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text('<manifest>' + ''.join(
                f'<project path="{path}" name="platform/{path}"/>'
                for path in CI.CACHE_PROJECTS) + '</manifest>')
            paths = CI.cache_paths(root)
            self.assertEqual(len(paths), len(CI.CACHE_PROJECTS) * 2)
            for path in paths:
                self.assertTrue(path.is_relative_to(root / ".repo"))
                self.assertTrue(path.name.endswith(".git"))
                path.mkdir(parents=True)
                (path / "fixture-pack").write_bytes(b"12345")
            self.assertEqual(CI.cache_size(paths), len(paths) * 5)
            output = root / "github-output"
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}), \
                    patch.object(CI.sys, "argv", ["ci", "cache-budget", str(root)]), \
                    patch.object(CI, "CACHE_LIMIT", 1), contextlib.redirect_stdout(io.StringIO()):
                CI.main()
            self.assertEqual(output.read_text().strip(), "save=false")
            with patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}), \
                    patch.object(CI.sys, "argv", ["ci", "cache-layout", str(root)]), \
                    patch.object(CI.shutil, "disk_usage", return_value=SimpleNamespace(free=0)), \
                    contextlib.redirect_stdout(io.StringIO()):
                CI.main()
            self.assertIn("restore=false", output.read_text())
            self.assertIn("paths<<CACHE_PATHS", output.read_text())
            self.assertIn("key=a17-source-git-v1-", output.read_text())
            manifest.write_text('<manifest/>')
            with self.assertRaises(ValueError):
                CI.cache_paths(root)

    def test_diagnostics_survive_failed_graph_and_exclude_secrets_and_big_intermediates(self):
        with fixture_directory() as root:
            (root / "out/ci").mkdir(parents=True)
            (root / "out/ci/graph-generation.log").write_text("FAILED: fixture")
            (root / "out/soong.environment.available").write_text("SECRET")
            (root / "out/build.ninja").write_text("not diagnostic data")
            CI.diagnostics(root, root / "evidence")
            self.assertEqual((root / "evidence/out/ci/graph-generation.log").read_text(), "FAILED: fixture")
            self.assertFalse((root / "evidence/out/soong.environment.available").exists())
            self.assertFalse((root / "evidence/out/build.ninja").exists())
            source = root / "large.log"
            source.write_text("0123456789")
            info = CI.bounded_copy(source, root / "tail.log", 4)
            self.assertTrue(info["tail_only"])
            self.assertEqual((root / "tail.log").read_text(), "6789")

    def test_graph_gate_precedes_compilation_and_diagnostics_are_unconditional(self):
        order = [WORKFLOW.index(text) for text in (
            '- name: Save selected source Git objects', '- name: Apply Samsung',
            '- name: Validate Rust sysroot and ABI tools', 'm --skip-ninja crosvm',
            'crosvm-android17-ci.py" graph', 'm -j2 -k0 crosvm')]
        self.assertEqual(order, sorted(order))
        self.assertNotIn('SKIP_ABI_CHECKS', WORKFLOW)
        for name in ('Collect bounded build diagnostics', 'Upload build diagnostics even on failure'):
            step = WORKFLOW.split('- name: ' + name, 1)[1].split('- name:', 1)[0]
            self.assertIn('if: always()', step)


if __name__ == "__main__":
    unittest.main(verbosity=2)
