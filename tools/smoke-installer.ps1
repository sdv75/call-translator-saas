param([Parameter(Mandatory=$true)][string]$StageDirectory, [Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$stage = (Resolve-Path -LiteralPath $StageDirectory).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
$build = [IO.Path]::GetFullPath((Join-Path $root 'build'))+[IO.Path]::DirectorySeparatorChar
if (-not $output.StartsWith($build, [StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $output)) {
    throw 'Use a new QA directory inside this project build folder'
}
$hostKey = 'Software\Google\Chrome\NativeMessagingHosts\org.call_translator.saas.local'
$uninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\CallTranslatorSaaS_is1'
foreach ($view in @([Microsoft.Win32.RegistryView]::Registry32,[Microsoft.Win32.RegistryView]::Registry64)) {
    $registry = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser,$view)
    try {
        foreach ($name in @($hostKey,$uninstallKey)) {
            $key = $registry.OpenSubKey($name)
            if ($key) { $key.Dispose(); throw 'An existing SaaS installation must not be replaced by the QA tool' }
        }
    } finally { $registry.Dispose() }
}
$installer = Join-Path $stage 'installer-output/CallTranslatorSetup.exe'
$manifest = Get-Content -LiteralPath (Join-Path $stage 'installer-manifest.json') -Raw | ConvertFrom-Json
if (-not $manifest.installer_compiled -or (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.installer_sha256) {
    throw 'Verified installer required'
}
New-Item -ItemType Directory -Path $output | Out-Null
$destination = Join-Path $output 'installed'
$installed = $false
$report = @{installer_installed=$false; native_manifest_registered=$false; uninstall_clean=$false;
    clean_windows_verified=$false; chrome_native_registration_verified=$false; full_meet_call_verified=$false}
try {
    $process = Start-Process -FilePath $installer -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-','/NOICONS',('/DIR="'+$destination+'"'),('/LOG="'+(Join-Path $output 'install.log')+'"')) -WindowStyle Hidden -PassThru -Wait
    # Even a partly failed installation may have created its own uninstaller.
    $installed = Test-Path -LiteralPath (Join-Path $destination 'unins000.exe')
    if ($process.ExitCode -ne 0 -or -not $installed) { throw 'Installer smoke failed' }
    $report.installer_installed = $true
    $registered = (Get-Item -LiteralPath ('HKCU:\'+$hostKey)).GetValue('')
    if ($registered -ne (Join-Path $destination 'native-host.json')) { throw 'Unexpected native registration' }
    $hostManifest = Get-Content -LiteralPath $registered -Raw | ConvertFrom-Json
    if ($hostManifest.name -ne 'org.call_translator.saas.local' -or $hostManifest.path -ne 'CallTranslatorLocal.exe' -or
        $hostManifest.allowed_origins.Count -ne 1 -or $hostManifest.allowed_origins[0] -ne 'chrome-extension://afdgmhaicjhehhhhlahpeinieglofgml/') {
        throw 'Installed native manifest mismatch'
    }
    $original = Get-FileHash -LiteralPath (Join-Path $stage 'CallTranslatorLocal.exe') -Algorithm SHA256
    $copied = Get-FileHash -LiteralPath (Join-Path $destination 'CallTranslatorLocal.exe') -Algorithm SHA256
    if ($original.Hash -ne $copied.Hash -or -not (Test-Path -LiteralPath (Join-Path $destination 'extension/offscreen.js'))) {
        throw 'Installed files mismatch'
    }
    $report.native_manifest_registered = $true
} finally {
    if ($installed) {
        # Resolved destination was checked inside build before invoking removal.
        $process = Start-Process -FilePath (Join-Path $destination 'unins000.exe') -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART',('/LOG="'+(Join-Path $output 'uninstall.log')+'"')) -WindowStyle Hidden -PassThru -Wait
        if ($process.ExitCode -ne 0) { throw 'QA uninstaller failed; inspect the QA install directory' }
        $deadline = [DateTime]::UtcNow.AddSeconds(30)
        do {
            $report.uninstall_clean = -not (Test-Path -LiteralPath ('HKCU:\'+$hostKey)) -and -not (Test-Path -LiteralPath ('HKCU:\'+$uninstallKey)) -and -not (Test-Path -LiteralPath (Join-Path $destination 'CallTranslatorLocal.exe'))
            if (-not $report.uninstall_clean) { Start-Sleep -Milliseconds 300 }
        } while (-not $report.uninstall_clean -and [DateTime]::UtcNow -lt $deadline)
    }
    $report | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'installer-smoke.json') -Encoding UTF8
}
if (-not $report.uninstall_clean) { throw 'QA installation cleanup incomplete' }
$report | ConvertTo-Json
