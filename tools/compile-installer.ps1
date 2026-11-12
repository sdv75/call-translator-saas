param(
    [Parameter(Mandatory=$true)][string]$PreparedDirectory,
    [Parameter(Mandatory=$true)][string]$StageDirectory,
    [Parameter(Mandatory=$true)][string]$PyAppLicense,
    [string]$Compiler
)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$prepared = (Resolve-Path -LiteralPath $PreparedDirectory).Path
$license = (Resolve-Path -LiteralPath $PyAppLicense).Path
$stage = [IO.Path]::GetFullPath($StageDirectory)
if (-not $Compiler) {
    $portable = Join-Path $root '.tools/inno-6.7.4/ISCC.exe'
    if (Test-Path -LiteralPath $portable) { $Compiler = $portable }
    else { $Compiler = (Get-Command ISCC -ErrorAction Stop).Source }
}
Push-Location $root
try {
    $identity = & uv run --frozen python -m tools.extension_id
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the pinned extension ID' }
    & uv run --frozen python -m tools.stage_installer --prepared $prepared --extension-id $identity --pyapp-license $license --output $stage
    if ($LASTEXITCODE -ne 0) { throw 'Installer staging failed' }
    & $Compiler /Qp ("/DStageDir="+$stage) (Join-Path $root 'installer/CallTranslator.iss')
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed' }
    $installer = Join-Path $stage 'installer-output/CallTranslatorSetup.exe'
    $report = @{installer_compiled=$true; installer_sha256=(Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant();
        installer_bytes=(Get-Item -LiteralPath $installer).Length; signed_release=$false;
        clean_windows_verified=$false; chrome_native_registration_verified=$false; full_meet_call_verified=$false}
    $report | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stage 'installer-manifest.json') -Encoding UTF8
    Write-Output 'Technical installer compiled. Installation, Chrome registration and clean-Windows checks remain separate.'
} finally { Pop-Location }
