[CmdletBinding()]
param()
$ErrorActionPreference='Stop'
$root=Split-Path -Parent $PSScriptRoot
$appInfo=Get-Content -LiteralPath (Join-Path $root 'config.json') -Raw | ConvertFrom-Json
$appName="SukiSU-Build-Center-$($appInfo.version)"
$distDir=Join-Path $root "dist\$($appInfo.version)"
$oldPythonPath=$env:PYTHONPATH
$env:PYTHONPATH=Join-Path $root '.build-deps'
Push-Location -LiteralPath $root
try {
    $webData=(Join-Path $root 'web')+';web'
    $configData=(Join-Path $root 'config.json')+';.'
    $iconPath=Join-Path $PSScriptRoot 'icon.ico'
    python -m PyInstaller --noconfirm --clean --onefile --windowed --name $appName --icon $iconPath --add-data $webData --add-data $configData --distpath $distDir --workpath build/windows --specpath build desktop.py
    if($LASTEXITCODE -ne 0){throw 'Windows-Build fehlgeschlagen.'}
    Get-FileHash -LiteralPath (Join-Path $distDir "$appName.exe") -Algorithm SHA256
} finally { Pop-Location; $env:PYTHONPATH=$oldPythonPath }
