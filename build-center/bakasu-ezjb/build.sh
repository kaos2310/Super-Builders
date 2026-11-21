#!/usr/bin/env bash
set -euo pipefail
h=$(cd "$(dirname "$0")" && pwd)
work=$(realpath -m "$1")
mkdir -p "$work" "$work/clang" "$work/ktools" "$work/out" "$work/Baseband-guard-common"
(
    cd "$h"
    sha256sum -c inputs.sha256
)

checkout() {
    local url=$1 pin=$2 path=$3
    git init -q "$path"
    git -C "$path" fetch --no-tags --depth=1 "$url" "$pin"
    git -C "$path" checkout -q --detach FETCH_HEAD
    [[ $(git -C "$path" rev-parse HEAD) == "$pin" ]]
}
fetch_archive() {
    local url=$1 path=$2
    curl -fLsS --retry 4 "$url" -o "$path.tar.gz"
    tar -xzf "$path.tar.gz" -C "$path"
}
common_pin=4bd1b41bff8bb87bed8c3621fa2bb5b2e96f5d8c
bakasu_pin=7b65bde0710b5e7c6f755545cb15a4abd417f3a8
checkout https://android.googlesource.com/kernel/common "$common_pin" "$work/common" & common_job=$!
fetch_archive https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+archive/382db94fa9597402b69e252c36bf9902cc283b82/clang-r487747c.tar.gz "$work/clang" & clang_job=$!
fetch_archive https://android.googlesource.com/kernel/prebuilts/build-tools/+archive/e905be252a53d20c52bd9e59df3ff8fdd46b9eab/linux-x86.tar.gz "$work/ktools" & ktools_job=$!
git clone --no-checkout https://github.com/Baka-SU/BakaSU.git "$work/BakaSU"
git -C "$work/BakaSU" checkout -q --detach "$bakasu_pin"
[[ $(git -C "$work/BakaSU" rev-list --count HEAD) == 4562 ]]
git -C "$work/BakaSU" apply --check "$h/BakaSU-35262-kernel-overlay.patch"
git -C "$work/BakaSU" apply "$h/BakaSU-35262-kernel-overlay.patch"
wait "$common_job"
wait "$clang_job"
wait "$ktools_job"
python3 "$h/overlay.py" "$work/common"
tar -xJf "$h/baseband-guard.tar.xz" -C "$work/Baseband-guard-common"
ln -s ../../BakaSU/kernel "$work/common/drivers/kernelsu"
ln -s ../../Baseband-guard-common "$work/common/security/baseband-guard"

export PATH="$work/clang/bin:$work/ktools/bin:$PATH"
export LD_LIBRARY_PATH="$work/ktools/lib64${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export KBUILD_BUILD_USER=build-user KBUILD_BUILD_HOST=build-host
export KBUILD_BUILD_TIMESTAMP='Mon Oct 19 08:59:36 UTC 2026'
compiler=$(clang --version)
grep -qF 'clang version 17.0.2' <<<"$compiler"
cp "$h/config-EZJB-ThinLTO.txt" "$work/out/.config"
args=(-C "$work/common" "O=$work/out" ARCH=arm64 LLVM=1 "-j$(nproc)")
make "${args[@]}" olddefconfig prepare headers_install
make "${args[@]}" Image modules
python3 "$h/verify_kernel_build.py" "$work/out"

mkdir -p "$work/out/android14-6.1/dist"
ln -s "$work/out/Module.symvers" "$work/out/android14-6.1/dist/Module.symvers"
bash "$h/strict-audit.sh" "$work" "$h/../ci/firmware/ezj1/strict-baseline.tsv" "$work/strict-audit" strict full
