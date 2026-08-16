#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request


TAG = os.environ.get("AOSP_TAG", "android-16.0.0_r4")
EXPECTED_TAG = "android-16.0.0_r4"


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def get_bytes(url: str) -> bytes:
    last = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Super-Builders-crosvm-ci"})
            with urllib.request.urlopen(req, timeout=60) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt < 3:
                time.sleep(attempt * 2)
    fail(f"failed to fetch {url}: {last}")


def gitiles_base(project: str, relpath: str) -> str:
    quoted = "/".join(urllib.parse.quote(part, safe="._-") for part in relpath.split("/") if part)
    return f"https://android.googlesource.com/{project}/+/refs/tags/{TAG}/{quoted}"


def fetch_text(project: str, relpath: str) -> str:
    raw = get_bytes(gitiles_base(project, relpath) + "?format=TEXT")
    try:
        return base64.b64decode(raw, validate=True).decode("utf-8")
    except Exception as exc:
        fail(f"invalid Gitiles TEXT payload for {project}/{relpath}: {exc}")


def fetch_dir(project: str, relpath: str, dest: Path) -> None:
    raw = get_bytes(gitiles_base(project, relpath) + "?format=JSON")
    prefix = b")]}'\n"
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        fail(f"invalid Gitiles JSON payload for {project}/{relpath}: {exc}")
    entries = data.get("entries") or []
    if not entries:
        fail(f"empty Gitiles directory for {project}/{relpath}")
    dest.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        name = entry.get("name")
        typ = entry.get("type")
        if not name or "/" in name or name in {".", ".."}:
            fail(f"unsafe Gitiles entry under {project}/{relpath}: {entry!r}")
        source = f"{relpath.rstrip('/')}/{name}"
        target = dest / name
        if typ == "tree":
            fetch_dir(project, source, target)
        elif typ == "blob":
            target.write_text(fetch_text(project, source), encoding="utf-8")
        else:
            fail(f"unsupported Gitiles entry type {typ!r} for {project}/{source}")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    import sys
    if len(sys.argv) != 2:
        fail("usage: prepare-crosvm-binder-deps.py <AOSP external/crosvm path>")
    if TAG != EXPECTED_TAG:
        fail(f"this provider closure is pinned to {EXPECTED_TAG}, got {TAG}")

    crosvm_root = Path(sys.argv[1]).resolve()
    if crosvm_root.name != "crosvm" or crosvm_root.parent.name != "external":
        fail(f"unexpected crosvm path: {crosvm_root}")
    aosp_root = crosvm_root.parents[1]
    if not (aosp_root / "frameworks/native/libs/binder/Android.bp").is_file():
        fail("frameworks/native libbinder source is missing")

    framework_bp = fetch_text("platform/frameworks/base", "core/java/Android.bp")
    for needle in (
        'name: "android-os-statsbootstrap-aidl"',
        '"android/os/IStatsBootstrapAtomService.aidl"',
        '"android/os/StatsBootstrapAtom.aidl"',
        '"android/os/StatsBootstrapAtomValue.aidl"',
    ):
        if needle not in framework_bp:
            fail(f"exact-tag frameworks/base provider drift: missing {needle}")

    nativehelper_bp = fetch_text("platform/libnativehelper", "Android.bp")
    if 'name: "jni_headers"' not in nativehelper_bp:
        fail("exact-tag libnativehelper no longer defines jni_headers")

    apexsupport_bp = fetch_text("platform/system/apex", "libs/libapexsupport/Android.bp")
    if 'name: "libapexsupport"' not in apexsupport_bp:
        fail("exact-tag system/apex no longer defines libapexsupport")
    apexsupport_header = fetch_text(
        "platform/system/apex", "libs/libapexsupport/include/android/apexsupport.h"
    )
    signature_tokens = (
        "AApexSupport_loadLibrary(",
        "const char *_Nonnull name",
        "const char *_Nonnull apexName",
        "int flag",
    )
    missing = [token for token in signature_tokens if token not in apexsupport_header]
    if missing:
        fail(f"exact-tag AApexSupport_loadLibrary signature drift: {missing}")

    stubs = aosp_root / "android-16-crosvm-build-stubs"
    stats = stubs / "statsbootstrap"
    jni = stubs / "jni_headers"
    apex = stubs / "apexsupport"
    for path in (stats, jni, apex):
        if path.exists():
            shutil.rmtree(path)

    aidl_names = (
        "IStatsBootstrapAtomService.aidl",
        "StatsBootstrapAtom.aidl",
        "StatsBootstrapAtomValue.aidl",
    )
    for name in aidl_names:
        write(
            stats / "android/os" / name,
            fetch_text("platform/frameworks/base", f"core/java/android/os/{name}"),
        )
    write(
        stats / "Android.bp",
        '''filegroup {
    name: "android-os-statsbootstrap-aidl",
    srcs: [
        "android/os/IStatsBootstrapAtomService.aidl",
        "android/os/StatsBootstrapAtom.aidl",
        "android/os/StatsBootstrapAtomValue.aidl",
    ],
    visibility: ["//frameworks/native/libs/binder"],
}
''',
    )

    fetch_dir("platform/libnativehelper", "include_jni", jni / "include_jni")
    if not (jni / "include_jni/jni.h").is_file():
        fail("exact-tag jni.h was not downloaded")
    write(
        jni / "Android.bp",
        '''cc_library_headers {
    name: "jni_headers",
    host_supported: true,
    export_include_dirs: ["include_jni"],
    native_bridge_supported: true,
    product_available: true,
    vendor_available: true,
    ramdisk_available: true,
    recovery_available: true,
    apex_available: [
        "//apex_available:platform",
        "//apex_available:anyapex",
    ],
    visibility: ["//visibility:public"],
    stl: "none",
    system_shared_libs: [],
    sdk_version: "minimum",
    min_sdk_version: "29",
}
''',
    )

    fetch_dir(
        "platform/system/apex",
        "libs/libapexsupport/include",
        apex / "include",
    )
    write(
        apex / "apexsupport_stub.c",
        '''__attribute__((visibility("default")))
void *AApexSupport_loadLibrary(const char *name, const char *apexName, int flag) {
    (void)name;
    (void)apexName;
    (void)flag;
    return (void *)0;
}
''',
    )
    write(
        apex / "Android.bp",
        '''cc_library_shared {
    name: "libapexsupport",
    srcs: ["apexsupport_stub.c"],
    export_include_dirs: ["include"],
    apex_available: ["//apex_available:platform"],
    visibility: ["//visibility:public"],
    stl: "none",
    system_shared_libs: ["libc"],
    installable: false,
}
''',
    )

    checks = {
        stats / "Android.bp": (
            'name: "android-os-statsbootstrap-aidl"',
            "IStatsBootstrapAtomService.aidl",
            "StatsBootstrapAtom.aidl",
            "StatsBootstrapAtomValue.aidl",
        ),
        jni / "Android.bp": ('name: "jni_headers"',),
        apex / "Android.bp": (
            'name: "libapexsupport"',
            'system_shared_libs: ["libc"]',
        ),
        apex / "apexsupport_stub.c": ("AApexSupport_loadLibrary",),
    }
    for path, needles in checks.items():
        text = path.read_text(encoding="utf-8")
        absent = [needle for needle in needles if needle not in text]
        if absent:
            fail(f"generated provider {path} is incomplete: {absent}")

    print(
        "Prepared minimal libbinder providers: "
        "android-os-statsbootstrap-aidl, jni_headers, libapexsupport"
    )


if __name__ == "__main__":
    main()
