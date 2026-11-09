[CmdletBinding()]
param(
    [string]$AndroidSdk='D:\StudioAndroid',
    [string]$JavaHome='D:\Android Studio\jbr'
)
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$work=Join-Path $root 'build\android'
$output=Join-Path $root 'dist'
$privateDir=Join-Path $root 'private'
New-Item -ItemType Directory -Path $work,$output,$privateDir -Force | Out-Null
$platform=Join-Path $AndroidSdk 'platforms\android-36\android.jar'
$buildTools=Join-Path $AndroidSdk 'build-tools\36.0.0'
$env:JAVA_HOME=$JavaHome
function Check-Exit([string]$Label) { if($LASTEXITCODE -ne 0){throw "$Label fehlgeschlagen: $LASTEXITCODE"} }
$classes=Join-Path $work 'classes'
New-Item -ItemType Directory -Path $classes -Force | Out-Null
$sources=@(Get-ChildItem -LiteralPath (Join-Path $root 'android\src') -Recurse -Filter '*.java' | ForEach-Object FullName)
& (Join-Path $JavaHome 'bin\javac.exe') --release 17 -encoding UTF-8 -classpath $platform -d $classes @sources
Check-Exit 'Java-Kompilierung'
$classFiles=@(Get-ChildItem -LiteralPath $classes -Recurse -Filter '*.class' | ForEach-Object FullName)
& (Join-Path $buildTools 'd8.bat') --min-api 29 --lib $platform --output $work @classFiles
Check-Exit 'DEX'
$compiled=Join-Path $work 'resources.zip'
& (Join-Path $buildTools 'aapt2.exe') compile --dir (Join-Path $root 'android\res') -o $compiled
Check-Exit 'Android-Ressourcen'
$assets=Join-Path $work 'assets'
New-Item -ItemType Directory -Path $assets -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'web') -Destination $assets -Recurse -Force
$unsigned=Join-Path $work 'unsigned.apk'
& (Join-Path $buildTools 'aapt2.exe') link -o $unsigned -I $platform --manifest (Join-Path $root 'android\AndroidManifest.xml') -A $assets --min-sdk-version 29 --target-sdk-version 35 --version-code 1 --version-name '1.0.0' $compiled
Check-Exit 'APK-Paket'
Push-Location -LiteralPath $work
try { & (Join-Path $buildTools 'aapt.exe') add $unsigned 'classes.dex'; Check-Exit 'DEX verpacken' } finally { Pop-Location }
python (Join-Path $PSScriptRoot 'normalize_apk.py') $unsigned
Check-Exit 'APK-Pfadnormalisierung'
$key=Join-Path $privateDir 'build-center.p12'
$passwordFile=Join-Path $privateDir 'signing-password.txt'
if(!(Test-Path -LiteralPath $key)) {
    $random=[byte[]]::new(32)
    [Security.Cryptography.RandomNumberGenerator]::Fill($random)
    $password=[Convert]::ToBase64String($random)
    [IO.File]::WriteAllText($passwordFile,$password)
    $env:KAOSLAB_CENTER_KEY_PASS=$password
    & (Join-Path $JavaHome 'bin\keytool.exe') -genkeypair -keystore $key -storetype PKCS12 -alias buildcenter -keyalg RSA -keysize 3072 -validity 36500 -storepass:env KAOSLAB_CENTER_KEY_PASS -dname 'CN=KAOSLAB Build Center, O=KAOSLAB, C=DE'
    Check-Exit 'Signierschlüssel'
} else { $env:KAOSLAB_CENTER_KEY_PASS=[IO.File]::ReadAllText($passwordFile).Trim() }
$aligned=Join-Path $work 'aligned.apk'
& (Join-Path $buildTools 'zipalign.exe') -f 4 $unsigned $aligned
Check-Exit 'ZIP-Ausrichtung'
$apk=Join-Path $output 'SukiSU-Build-Center-1.0.0.apk'
try {
    & (Join-Path $buildTools 'apksigner.bat') sign --ks $key --ks-key-alias buildcenter --ks-pass env:KAOSLAB_CENTER_KEY_PASS --v4-signing-enabled false --out $apk $aligned
    Check-Exit 'APK-Signierung'
} finally { Remove-Item Env:KAOSLAB_CENTER_KEY_PASS -ErrorAction SilentlyContinue }
& (Join-Path $buildTools 'apksigner.bat') verify --verbose --print-certs $apk
Check-Exit 'Signaturprüfung'
& (Join-Path $buildTools 'aapt.exe') dump badging $apk | Select-String '^(package:|sdkVersion:|targetSdkVersion:|application-label:|launchable-activity:)'
Get-FileHash -LiteralPath $apk -Algorithm SHA256
