#!/usr/bin/env bash
set -euo pipefail
out=$1
mkdir -p "$out"
url=https://github.com/kaos2310/Super-Builders/releases/download/s928b-ezj1-suki35004-susfs2.4.0-1439545f-f76b81f2-hidden-name-readdir-v2-r44836464612
get_asset() {
    local name=$1 output=$2 hash=$3
    curl --silent --show-error --fail --location --retry 4 "$url/$name" -o "$out/$output"
    (cd "$out"; printf '%s  %s\n' "$hash" "$output" | sha256sum -c)
}
case "$2" in
    kernel)
        get_asset 6.1.162-android14-2026-03-SukiSU-35004-UIDGate-v1-Runtime-v1-KPM-GunyahAdaptive-v1-Reclaim-v1-OpenRedirect-Test-KMI-full-strict-strict-S928BXXS6EZJ1-EUX-AnyKernel3.zip kernel.zip 5ef1132b7b8a2abc27fcc1cc041afe766dc5567f742e0c0f65ee8997e496e2ef
        ;;
    modules)
        get_asset ReSuSFS-v26.10.23-KAOSLAB-SUSFS2.4.0-Runtime1-r3-Nova35004-arm64.zip resusfs.zip 5fe9e0d35a06a498f0d2aad6549ce6d60cc7022887bd54cc82bc1530272ae421
        get_asset ZeroMount-Guard6.13-BRENE76-SUSFS2.4.0-SukiSUNova35004-arm64.zip zeromount.zip 6adf97a62b3bec57c0357bc08ff93e0096f42d2ea42bc2e3952b6d695cc91e70
        ;;
    *) exit 64;;
esac
