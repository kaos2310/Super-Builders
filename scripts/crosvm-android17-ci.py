#!/usr/bin/env python3
"""Fail-closed A17 toolchain/target graph checks and bounded CI evidence/cache."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

# Cache Git metadata only, never patched checkouts or generated build outputs.
# Both halves of repo's shared-object layout are needed for reusable refs/objects.
CACHE_PROJECTS = ("build/soong", "external/crosvm",
                  "external/rust/android-crates-io", "external/mesa3d")
# Run 33970092714 saved 190 MiB but had only 1.38 GiB free on RUNNER_TEMP.
# A speculative 4 GiB restore reservation prevented this small cache loading.
CACHE_LIMIT = 256 * 1024**2
ABI_TOOLS = ("header-abi-dumper", "header-abi-linker", "header-abi-diff")


def bp_module(source, name):
    # Tokenize strings before comments so //apex_available remains intact.
    tokens = re.findall(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|[{}]|[^{}"/]+|/',
                        source, re.S)
    clean = "".join(t for t in tokens if not t.startswith(("//", "/*")))
    blocks, start, depth = [], 0, 0
    for match in re.finditer(r'"(?:\\.|[^"\\])*"|[{}]', clean):
        token = match.group()
        if token == "{":
            if depth == 0:
                start = match.start()
            depth += 1
        elif token == "}":
            depth -= 1
            if depth == 0:
                block = clean[start:match.end()]
                if re.search(r'\bname\s*:\s*"' + re.escape(name) + '"', block):
                    blocks.append(block)
    if depth or len(blocks) != 1:
        raise ValueError(f"expected one complete module {name}, found {len(blocks)}")
    return blocks[0]


def rust_contract(source):
    defaults = bp_module(source, "rust_sysroot_defaults")
    apex = re.search(r'\bapex_available\s*:\s*\[([^]]*)\]', defaults)
    if not apex or not all(f'"{entry}"' in apex[1] for entry in (
            "//apex_available:platform", "//apex_available:anyapex")):
        raise ValueError("rust_sysroot_defaults lost platform/anyapex availability")
    for prop in ("no_stdlibs", "host_supported", "vendor_available",
                 "product_available", "recovery_available", "sysroot"):
        if not re.search(r'\b' + prop + r'\s*:\s*true\b', defaults):
            raise ValueError(f"rust_sysroot_defaults missing {prop}")
    if not re.search(r'\bedition\s*:\s*"2024"', defaults):
        raise ValueError("rust_sysroot_defaults missing edition 2024")
    for module in ("libcore.rust_sysroot", "liballoc.rust_sysroot",
                   "libcompiler_builtins.rust_sysroot", "rust_static_cc_lib_defaults"):
        bp_module(source, module)


def toolchain_check(root):
    errors = []
    def check(label, action):
        try:
            result = action()
            print(f"PASS {label}" + (f": {result}" if result else ""), flush=True)
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            errors.append(f"{label}: {exc}")
    def require_file(relative, executable=False):
        path = root / relative
        if not path.is_file() or (executable and not os.access(path, os.X_OK)):
            raise ValueError(f"missing {'executable' if executable else 'file'}: {relative}")
    def version(relative, expected=None):
        require_file(relative, True)
        output = subprocess.check_output([str(root / relative), "--version"],
                                         text=True, stderr=subprocess.STDOUT, timeout=30).strip()
        if expected and not re.search(r'\brustc ' + re.escape(expected) + r'\b', output):
            raise ValueError(f"unexpected compiler version: {output}")
        return output
    def config():
        source = (root / "build/soong/rust/config/global.go").read_text()
        for name, value in (("RustDefaultBase", "prebuilts/rust-toolchain/"),
                            ("RustDefaultVersion", "1.93.1")):
            if not re.search(r'\b' + name + r'\s*=\s*"' + re.escape(value) + '"', source):
                raise ValueError(f"unexpected {name}; update the pinned preflight")
        for name in ("RUST_PREBUILTS_BASE", "RUST_PREBUILTS_VERSION"):
            if os.environ.get(name):
                raise ValueError(f"unexpected toolchain override: {name}")
    check("Soong Rust configuration", config)
    check("Rust sysroot module/APEX contract", lambda: rust_contract(
        (root / "prebuilts/rust-toolchain/linux-x86/Android.bp").read_text()))
    for host in ("linux-x86", "linux-musl-x86"):
        base = f"prebuilts/rust-toolchain/{host}"
        check(f"{host} module provider", lambda base=base: require_file(base + "/Android.bp"))
        check(f"{host} rustc", lambda base=base: version(base + "/1.93.1/bin/rustc", "1.93.1"))
        for tool in ("rustfmt", "clippy-driver"):
            check(f"{host} {tool}", lambda base=base, tool=tool:
                  require_file(base + "/1.93.1/bin/" + tool, True))
    for crate in ("core", "alloc", "std"):
        relative = f"prebuilts/rust-toolchain/linux-x86/1.93.1/lib/rustlib/src/rust/library/{crate}/src/lib.rs"
        check(f"Rust {crate} sources", lambda relative=relative: require_file(relative))
    for tool in ABI_TOOLS:
        relative = f"prebuilts/clang-tools/linux-x86/bin/{tool}"
        check(tool, lambda relative=relative: version(relative))
    check("Ninja graph inspector", lambda: version("prebuilts/build-tools/linux-x86/bin/ninja"))
    for module in ("libbionic_panic_abort", "liblibc_alloc_rust"):
        def consumer(module=module):
            block = bp_module((root / "system/librustutils/no_std/Android.bp").read_text(), module)
            if not re.search(r'defaults\s*:\s*\[[^]]*"rust_sysroot_defaults"', block):
                raise ValueError(f"{module} no longer inherits rust_sysroot_defaults")
        check(module, consumer)
    if errors:
        raise ValueError("Toolchain/provider errors:\n" + "\n".join(errors))


def failing_command(line):
    # ALLOW_MISSING_DEPENDENCIES emits executable Error rules; a Ninja dry run
    # alone reports success for them. Inspect *all* reachable commands as well.
    return bool(re.search(r'\bmissing dependencies:', line) or
                re.search(r'&&\s*false\s*[;)]*\s*$', line))


def graph_check(root, ninja, graph, destination):
    if not graph.is_file():
        raise ValueError(f"missing combined Ninja graph: {graph}")
    destination.mkdir(parents=True, exist_ok=True)
    base = [str(ninja), "-f", str(graph)]
    # Stream the potentially large command list, retain only actionable errors.
    count, failures = 0, set()
    stderr_path = destination / "ninja-commands-stderr.txt"
    with stderr_path.open("w", encoding="utf-8") as stderr:
        proc = subprocess.Popen(base + ["-t", "commands", "crosvm"], cwd=root,
                                stdout=subprocess.PIPE, stderr=stderr, text=True,
                                encoding="utf-8", errors="replace")
        with proc.stdout:
            for line in proc.stdout:
                count += 1
                if failing_command(line):
                    failures.add(line.strip())
        command_status = proc.wait()
    # -n never executes commands, including manifest-regeneration commands.
    dry_log = destination / "ninja-dry-run.txt"
    with dry_log.open("w", encoding="utf-8") as output:
        dry = subprocess.run(base + ["-n", "-v", "-k", "0", "crosvm"], cwd=root,
                             stdout=output, stderr=subprocess.STDOUT, timeout=300)
    # Ninja's commands tool can omit validation edges (|@). The verbose dry
    # run also expands those commands, so audit both views of the target graph.
    with dry_log.open(encoding="utf-8", errors="replace") as output:
        for line in output:
            line = re.sub(r'^\[\d+/\d+\]\s*', '', line).strip()
            if failing_command(line):
                failures.add(line)
    report = {"graph": str(graph), "reachable_commands": count,
              "commands_exit": command_status, "dry_run_exit": dry.returncode,
              "reachable_error_rules": sorted(failures)}
    (destination / "graph-audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2), flush=True)
    if command_status or dry.returncode or failures or not count:
        raise ValueError("crosvm target graph failed preflight; see graph-audit and ninja logs")


def cache_paths(root):
    manifest = root / ".repo/manifests/default.xml"
    projects = {p.get("path", p.get("name")): p.get("name")
                for p in ET.parse(manifest).getroot().findall("project")}
    paths = []
    for path in CACHE_PROJECTS:
        name = projects.get(path)
        if not name or ".." in Path(name).parts or Path(name).is_absolute():
            raise ValueError(f"invalid cache project in manifest: {path}")
        paths.extend([root / ".repo/projects" / (path + ".git"),
                      root / ".repo/project-objects" / (name + ".git")])
    return paths


def cache_size(paths):
    total = 0
    for path in paths:
        if not path.is_dir():
            raise ValueError(f"cache source missing: {path}")
        for base, dirs, files in os.walk(path, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(base) / d).is_symlink()]
            total += sum((Path(base) / f).lstat().st_size for f in files)
    return total


def bounded_copy(source, destination, limit):
    size = source.stat().st_size
    with source.open("rb") as src, destination.open("wb") as dst:
        if size > limit:
            src.seek(size - limit)
        shutil.copyfileobj(src, dst)
    return {"source": str(source), "bytes": size, "tail_only": size > limit}


def diagnostics(root, destination):
    destination.mkdir(parents=True, exist_ok=True)
    # Explicit allowlist: no credentials, environment dumps, Git configs or
    # multi-GB Ninja/Soong intermediates. At most 2 MiB per selected file.
    patterns = ("out/ci/*.txt", "out/ci/*.json", "out/ci/*.log",
                "out/platform-build-identity.txt", "out/last_kati_suffix",
                "out/soong.log", "out/error.log", "out/verbose.log.gz",
                "out/soong/soong.variables", ".repo/manifests/default.xml",
                "prebuilts/rust-toolchain/*/Android.bp",
                "external/google-highway/Android.bp",
                "android-17-crosvm-build-stubs/binder_native_aidl/Android.bp",
                "android-17-crosvm-build-stubs/binder_native_aidl/source-audit.json",
                "android-17-crosvm-build-stubs/binder_native_aidl/**/*.aidl",
                "system/librustutils/no_std/Android.bp")
    index = []
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            if not path.is_file():
                continue
            # Truncating compressed data makes it unreadable: skip oversized gz.
            if path.suffix == ".gz" and path.stat().st_size > 2 * 1024**2:
                index.append({"source": str(path), "skipped": "compressed log exceeds 2 MiB"})
                continue
            dest = destination / path.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            index.append(bounded_copy(path, dest, 2 * 1024**2))
    (destination / "index.json").write_text(json.dumps(index, indent=2) + "\n")
    # Record the actual synced revisions, including the late provider closure.
    manifest = root / ".repo/manifests/default.xml"
    if manifest.is_file():
        with (destination / "synced-revisions.tsv").open("w") as output:
            for project in ET.parse(manifest).getroot().findall("project"):
                path = project.get("path", project.get("name", ""))
                if not (root / path / ".git").exists():
                    continue
                result = subprocess.run(["git", "-C", str(root / path), "rev-parse", "HEAD"],
                                        capture_output=True, text=True, timeout=10)
                output.write(f"{path}\t{result.stdout.strip() if not result.returncode else 'UNRESOLVED'}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("toolchain", "graph", "cache-layout", "cache-budget", "diagnostics"))
    parser.add_argument("root", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    destination = args.destination or root / "out/ci"
    if args.mode == "toolchain":
        toolchain_check(root)
    elif args.mode == "graph":
        suffix = (root / "out/last_kati_suffix").read_text().strip()
        if not re.fullmatch(r'-module_arm64[^/\\\s]*', suffix):
            raise ValueError(f"unexpected Kati suffix: {suffix!r}")
        graph_check(root, root / "prebuilts/build-tools/linux-x86/bin/ninja",
                    root / "out" / f"combined{suffix}.ninja", destination)
    elif args.mode in ("cache-layout", "cache-budget"):
        paths = cache_paths(root)
        # actions/cache stages archives under RUNNER_TEMP, which the runner
        # re-exports from its context (a step env override cannot relocate it).
        free = shutil.disk_usage(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())).free
        margin = 1024**3
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            if args.mode == "cache-layout":
                digest = hashlib.sha256((root / ".repo/manifests/default.xml").read_bytes()
                                        + "\n".join(CACHE_PROJECTS).encode()).hexdigest()[:20]
                output.write(f"key=a17-source-git-v1-{digest}\npaths<<CACHE_PATHS\n")
                output.write("\n".join(map(str, paths)) + "\nCACHE_PATHS\n")
                output.write(f"restore={'true' if free >= CACHE_LIMIT + margin else 'false'}\n")
                print(f"Cache archive staging: {free} bytes free; restore requires {CACHE_LIMIT + margin}")
            else:
                size = cache_size(paths)
                print(f"Selected source cache: {size} bytes; limit {CACHE_LIMIT} bytes")
                output.write(f"save={'true' if size <= CACHE_LIMIT and free >= size + margin else 'false'}\n")
    else:
        diagnostics(root, destination)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
