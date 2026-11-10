[CmdletBinding()]
param([string]$AndroidSdk=$env:ANDROID_HOME)
$ErrorActionPreference='Stop'
if(!$AndroidSdk){throw 'AndroidSdk bzw. ANDROID_HOME angeben.'}
$env:ANDROID_HOME=$AndroidSdk
$env:ANDROID_SDK_ROOT=$AndroidSdk
$native=Join-Path $PSScriptRoot 'native-inputs'
$manager=Join-Path $PSScriptRoot 'SukiSU\manager'
if(!(Test-Path -LiteralPath $manager)){throw 'Das vollständige SukiSU-EZJ1-Quell-ZIP verwenden.'}
Push-Location -LiteralPath $manager
try {
    & .\gradlew.bat --no-daemon --max-workers=2 '-Pandroid.onlyEnableUnitTestForTheTestedBuildType=false' '-PKSU_BUILD_CODE=41168' '-PKSU_BUILD_COMMIT=674aa00c18adc3d7ef4069c03018d6194230865a' '-PKSU_BUILD_NAME=v4.3.0-r2-EZJ1-runtime1' '-PKSU_PACKAGE_NAME=com.kaoslab.sukisu.manager' '-PKSU_NAME=SukiSU EZJ1' '-PKSU_ABIS=arm64-v8a' "-PKSU_PINNED_KPM_DIR=$native" :app:testReleaseUnitTest --tests com.sukisu.ultra.data.repository.SusfsRuntimeRepositoryTest :app:assembleRelease
    if($LASTEXITCODE -ne 0){throw 'Manager-Build fehlgeschlagen.'}
} finally { Pop-Location }
