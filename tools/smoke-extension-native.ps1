param([Parameter(Mandatory=$true)][string]$StageDirectory, [Parameter(Mandatory=$true)][string]$OutputDirectory, [switch]$UseExistingRegistration)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$stage = (Resolve-Path -LiteralPath $StageDirectory).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
$build = [IO.Path]::GetFullPath((Join-Path $root 'build'))+[IO.Path]::DirectorySeparatorChar
if (-not $output.StartsWith($build,[StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $output)) {
    throw 'Use a new native QA directory inside the project build folder'
}
$name = 'Software\Google\Chrome\NativeMessagingHosts\org.call_translator.saas.local'
$existingHost = $null
foreach ($view in @([Microsoft.Win32.RegistryView]::Registry32,[Microsoft.Win32.RegistryView]::Registry64)) {
    $registry = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::CurrentUser,$view)
    try {
        $existing = $registry.OpenSubKey($name)
        if ($existing) {
            $candidate = [string]$existing.GetValue('')
            $existing.Dispose()
            if (-not $UseExistingRegistration) { throw 'Existing SaaS native registration must not be replaced' }
            if ($existingHost -and $existingHost -ne $candidate) { throw 'Ambiguous existing SaaS registration' }
            $existingHost = $candidate
        }
    } finally { $registry.Dispose() }
}
$hostFile = Join-Path $stage 'native-host.json'
if ($existingHost) { $hostFile = $existingHost }
$manifest = Get-Content -LiteralPath $hostFile -Raw | ConvertFrom-Json
if ($manifest.name -ne 'org.call_translator.saas.local' -or $manifest.path -ne 'CallTranslatorLocal.exe' -or
    $manifest.allowed_origins.Count -ne 1 -or $manifest.allowed_origins[0] -ne 'chrome-extension://afdgmhaicjhehhhhlahpeinieglofgml/') {
    throw 'Unexpected staged native manifest'
}
if ($existingHost) {
    $installedExe = Join-Path (Split-Path -Parent $hostFile) 'CallTranslatorLocal.exe'
    if ((Get-FileHash -LiteralPath $installedExe -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath (Join-Path $stage 'CallTranslatorLocal.exe') -Algorithm SHA256).Hash) {
        throw 'Existing native binary differs from verified staged binary'
    }
}
New-Item -ItemType Directory -Path $output | Out-Null
$key = 'HKCU:\'+$name
if (-not $existingHost) {
    New-Item -Path $key -Force | Out-Null
    Set-Item -LiteralPath $key -Value $hostFile
}
try {
    & node (Join-Path $PSScriptRoot 'smoke_extension_native.cjs') $stage $output (Join-Path $root 'build/local-voices')
    if ($LASTEXITCODE -ne 0) { throw 'Chrome/native integration verification failed' }
} finally {
    $registered = if (-not $existingHost) { Get-Item -LiteralPath $key -ErrorAction SilentlyContinue } else { $null }
    if ($registered -and $registered.GetValue('') -eq $hostFile) {
        $registered.Close()
        Remove-Item -LiteralPath $key
    } elseif ($registered) { $registered.Close(); Write-Warning 'Native registration changed externally; left untouched' }
}
