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


TAG = os.environ.get("AOSP_TAG", "android-17.0.0_r1")
EXPECTED_TAG = "android-17.0.0_r1"
VIRT_PROJECT = "platform/packages/modules/Virtualization"


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


def require_tokens(label: str, text: str, needles: tuple[str, ...]) -> None:
    missing = [needle for needle in needles if needle not in text]
    if missing:
        fail(f"{label} drift/incomplete: missing {missing}")


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

    gpu_display_bp_path = crosvm_root / "gpu_display/Android.bp"
    if not gpu_display_bp_path.is_file():
        fail("external/crosvm/gpu_display/Android.bp is missing")
    gpu_display_bp = gpu_display_bp_path.read_text(encoding="utf-8")
    require_tokens(
        "external/crosvm gpu_display provider contract",
        gpu_display_bp,
        (
            'name: "libgpu_display"',
            'android: {',
            '"libcrosvm_android_display_client"',
        ),
    )

    # Android 17 keeps the three StatsBootstrap AIDL contracts but no longer
    # publishes the old source filegroup from core/java/Android.bp. Validate
    # the contracts directly, then recreate only that filegroup below.
    for name in (
        "IStatsBootstrapAtomService.aidl",
        "StatsBootstrapAtom.aidl",
        "StatsBootstrapAtomValue.aidl",
    ):
        require_tokens(
            f"exact-tag frameworks/base {name}",
            fetch_text("platform/frameworks/base", f"core/java/android/os/{name}"),
            ("package android.os;",),
        )

    nativehelper_bp = fetch_text("platform/libnativehelper", "Android.bp")
    require_tokens(
        "exact-tag libnativehelper provider",
        nativehelper_bp,
        ('name: "jni_headers"',),
    )

    apexsupport_bp = fetch_text("platform/system/apex", "libs/libapexsupport/Android.bp")
    require_tokens(
        "exact-tag system/apex provider",
        apexsupport_bp,
        ('name: "libapexsupport"',),
    )
    apexsupport_header = fetch_text(
        "platform/system/apex", "libs/libapexsupport/include/android/apexsupport.h"
    )
    require_tokens(
        "exact-tag AApexSupport_loadLibrary signature",
        apexsupport_header,
        (
            "AApexSupport_loadLibrary(",
            "const char *_Nonnull name",
            "const char *_Nonnull apexName",
            "int flag",
        ),
    )

    virt_aidl_upstream_bp = fetch_text(
        VIRT_PROJECT, "android/virtualizationservice/aidl/Android.bp"
    )
    require_tokens(
        "exact-tag virtualization AIDL provider",
        virt_aidl_upstream_bp,
        (
            'name: "android.system.virtualizationcommon"',
            'name: "android.system.virtualizationservice"',
            'name: "android.system.virtualizationservice_internal"',
            '"android.system.virtualizationcommon"',
            '"android.system.virtualizationservice"',
        ),
    )

    display_upstream_bp = fetch_text(
        VIRT_PROJECT, "libs/android_display_backend/Android.bp"
    )
    require_tokens(
        "exact-tag crosvm Android display provider",
        display_upstream_bp,
        (
            'name: "libcrosvm_android_display_service"',
            'name: "libcrosvm_android_display_client"',
            '"android.system.virtualizationservice_internal-ndk"',
            '"android.system.virtualizationcommon-ndk"',
            '"android.system.virtualizationservice-ndk"',
            '"libbinder_ndk"',
            '"libnativewindow"',
            '"libcutils"',
        ),
    )

    stubs = aosp_root / "android-17-crosvm-build-stubs"
    stats = stubs / "statsbootstrap"
    jni = stubs / "jni_headers"
    apex = stubs / "apexsupport"
    virt_aidl = stubs / "virtualization_aidl"
    display = stubs / "android_display_backend"
    for path in (stats, jni, apex, virt_aidl, display):
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

    for interface in (
        "virtualizationcommon",
        "virtualizationservice",
        "virtualizationservice_internal",
    ):
        fetch_dir(
            VIRT_PROJECT,
            f"android/virtualizationservice/aidl/android/system/{interface}",
            virt_aidl / "android/system" / interface,
        )
    write(
        virt_aidl / "Android.bp",
        '''aidl_interface {
    name: "android.system.virtualizationcommon",
    srcs: ["android/system/virtualizationcommon/**/*.aidl"],
    unstable: true,
    backend: {
        java: { enabled: false },
        cpp: { enabled: false },
        rust: { enabled: false },
        ndk: {
            enabled: true,
            apex_available: [
                "com.android.virt",
                "com.android.compos",
            ],
        },
    },
}

aidl_interface {
    name: "android.system.virtualizationservice",
    srcs: ["android/system/virtualizationservice/**/*.aidl"],
    imports: ["android.system.virtualizationcommon"],
    unstable: true,
    backend: {
        java: { enabled: false },
        cpp: { enabled: false },
        rust: { enabled: false },
        ndk: {
            enabled: true,
            apex_available: [
                "com.android.virt",
                "com.android.compos",
            ],
        },
    },
}

aidl_interface {
    name: "android.system.virtualizationservice_internal",
    srcs: ["android/system/virtualizationservice_internal/**/*.aidl"],
    imports: [
        "android.system.virtualizationcommon",
        "android.system.virtualizationservice",
    ],
    unstable: true,
    backend: {
        java: { enabled: false },
        cpp: { enabled: false },
        rust: { enabled: false },
        ndk: {
            enabled: true,
            apex_available: ["com.android.virt"],
        },
    },
}
''',
    )

    fetch_dir(VIRT_PROJECT, "libs/android_display_backend", display)
    write(
        display / "Android.bp",
        '''aidl_interface {
    name: "libcrosvm_android_display_service",
    srcs: [
        "aidl/android/crosvm/ICrosvmAndroidDisplayService.aidl",
    ],
    include_dirs: [
        "frameworks/native/aidl/gui",
    ],
    local_include_dir: "aidl",
    unstable: true,
    backend: {
        java: { enabled: false },
        cpp: { enabled: false },
        rust: { enabled: false },
        ndk: {
            enabled: true,
            additional_shared_libraries: [
                "libnativewindow",
            ],
            apex_available: [
                "//apex_available:platform",
                "com.android.virt",
            ],
        },
    },
}

cc_library_static {
    name: "libcrosvm_android_display_client",
    srcs: [
        "crosvm_android_display_client.cpp",
        "surface_control_dl.cpp",
    ],
    whole_static_libs: [
        "libcrosvm_android_display_service-ndk",
        "android.system.virtualizationservice_internal-ndk",
        "android.system.virtualizationcommon-ndk",
        "android.system.virtualizationservice-ndk",
    ],
    static_libs: [
        "libbase",
    ],
    shared_libs: [
        "libbinder_ndk",
        "libnativewindow",
        "libcutils",
    ],
    apex_available: [
        "//apex_available:platform",
        "com.android.virt",
    ],
    visibility: ["//visibility:public"],
}
''',
    )

    required_files = (
        virt_aidl / "android/system/virtualizationservice_internal/IVirtualizationServiceInternal.aidl",
        display / "aidl/android/crosvm/ICrosvmAndroidDisplayService.aidl",
        display / "crosvm_android_display_client.cpp",
        display / "surface_control_dl.cpp",
        display / "surface_control_dl.h",
        display / "surface_control_abi.h",
    )
    missing_files = [str(path) for path in required_files if not path.is_file()]
    if missing_files:
        fail(f"generated Android display provider files are missing: {missing_files}")

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
        virt_aidl / "Android.bp": (
            'name: "android.system.virtualizationcommon"',
            'name: "android.system.virtualizationservice"',
            'name: "android.system.virtualizationservice_internal"',
        ),
        display / "Android.bp": (
            'name: "libcrosvm_android_display_service"',
            'name: "libcrosvm_android_display_client"',
            '"android.system.virtualizationservice_internal-ndk"',
            '"android.system.virtualizationcommon-ndk"',
            '"android.system.virtualizationservice-ndk"',
        ),
    }
    for path, needles in checks.items():
        text = path.read_text(encoding="utf-8")
        absent = [needle for needle in needles if needle not in text]
        if absent:
            fail(f"generated provider {path} is incomplete: {absent}")

    print(
        "Prepared crosvm provider closure: "
        "android-os-statsbootstrap-aidl, jni_headers, libapexsupport, "
        "android.system.virtualizationcommon-ndk, "
        "android.system.virtualizationservice-ndk, "
        "android.system.virtualizationservice_internal-ndk, "
        "libcrosvm_android_display_service-ndk, "
        "libcrosvm_android_display_client"
    )


if __name__ == "__main__":
    main()
