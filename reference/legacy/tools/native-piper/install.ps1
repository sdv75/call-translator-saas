param([string]$ExtensionId, [string]$ExtensionPath, [string]$InstallRoot = 'E:\Piper')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Windows is required.' }
$source = Join-Path $PSScriptRoot 'PiperHost'
if (-not (Test-Path -LiteralPath (Join-Path $source 'PiperHost.exe'))) { throw 'PiperHost.exe is missing. Extract the complete installation archive first.' }
$ids = @()
if ($ExtensionId) {
    if ($ExtensionId -notmatch '^[a-p]{32}$') { throw 'Invalid Chrome extension ID.' }
    $ids += $ExtensionId
}
if (-not $ExtensionPath) {
    $pathFile = Join-Path $PSScriptRoot 'extension-path.txt'
    if (Test-Path -LiteralPath $pathFile) { $ExtensionPath = (Get-Content -LiteralPath $pathFile -Raw -Encoding UTF8).Trim() }
}
# Read only extension IDs/paths; never print or copy Chrome profile contents.
$chromeData = Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data'
if ($ExtensionPath -and (Test-Path -LiteralPath $chromeData)) {
    foreach ($profile in Get-ChildItem -LiteralPath $chromeData -Directory) {
        foreach ($name in @('Secure Preferences', 'Preferences')) {
            $preferences = Join-Path $profile.FullName $name
            if (-not (Test-Path -LiteralPath $preferences)) { continue }
            try {
                $settings = (Get-Content -LiteralPath $preferences -Raw -Encoding UTF8 | ConvertFrom-Json).extensions.settings
                foreach ($entry in $settings.PSObject.Properties) {
                    if ($entry.Name -match '^[a-p]{32}$' -and $entry.Value.path -and
                        [IO.Path]::GetFullPath($entry.Value.path).TrimEnd('\') -eq [IO.Path]::GetFullPath($ExtensionPath).TrimEnd('\')) {
                        $ids += $entry.Name
                    }
                }
            } catch { continue }
        }
    }
}
$ids = @($ids | Sort-Object -Unique)
if (-not $ids.Count) { throw 'Chrome extension was not found. Run install.ps1 -ExtensionId <ID from chrome://extensions>.' }
$destination = [IO.Path]::GetFullPath($InstallRoot).TrimEnd('\')
$driveRoot = [IO.Path]::GetPathRoot($destination)
if ($destination.Length -le $driveRoot.Length) { throw 'Choose a dedicated installation directory, not a drive root.' }
$requiredBytes = (Get-ChildItem -LiteralPath $source -Recurse -File | Measure-Object -Property Length -Sum).Sum
if ([IO.DriveInfo]::new($driveRoot).AvailableFreeSpace -lt ($requiredBytes + 64MB)) {
    throw ('Not enough free space on ' + $driveRoot + '. Required bytes: ' + ($requiredBytes + 64MB))
}
$version = 'v1-' + [DateTime]::Now.ToString('yyyyMMdd-HHmmss-fffffff')
$versionsRoot = Join-Path $destination 'versions'
$versionDir = Join-Path $versionsRoot $version
New-Item -ItemType Directory -Path $versionsRoot -Force | Out-Null
New-Item -ItemType Directory -Path $versionDir | Out-Null
$exe = Join-Path $versionDir 'PiperHost.exe'
try {
    foreach ($entry in Get-ChildItem -LiteralPath $source) {
        Copy-Item -LiteralPath $entry.FullName -Destination $versionDir -Recurse
    }
    & $exe --self-test
    if ($LASTEXITCODE -ne 0) { throw 'Native Piper self-test failed. Existing installation was not changed.' }
} catch {
    # Only remove the unique directory just created by this installation attempt.
    $resolvedAttempt = [IO.Path]::GetFullPath($versionDir)
    $resolvedParent = [IO.Path]::GetFullPath($versionsRoot)
    if ([IO.Directory]::GetParent($resolvedAttempt).FullName -eq $resolvedParent -and
        [IO.Path]::GetFileName($resolvedAttempt) -eq $version) {
        Remove-Item -LiteralPath $resolvedAttempt -Recurse -Force
    }
    throw
}
$manifest = @{
    name = 'org.call_translator.piper'
    description = 'Call Translator native Piper'
    path = $exe
    type = 'stdio'
    allowed_origins = @($ids | ForEach-Object { 'chrome-extension://' + $_ + '/' })
} | ConvertTo-Json -Depth 4
$utf8 = [Text.UTF8Encoding]::new($false)
$hostManifest = Join-Path $versionDir 'org.call_translator.piper.json'
[IO.File]::WriteAllText($hostManifest, $manifest, $utf8)
$registryPath = 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\org.call_translator.piper'
$existing = Get-Item -LiteralPath $registryPath -ErrorAction SilentlyContinue
if ($existing) {
    $previousManifest = $existing.GetValue('')
    $backupPath = Join-Path $destination ('registration-before-' + $version + '.json')
    [IO.File]::WriteAllText($backupPath, (@{previousManifest = $previousManifest} | ConvertTo-Json), $utf8)
}
New-Item -Path $registryPath -Force | Out-Null
Set-Item -LiteralPath $registryPath -Value $hostManifest
Write-Output ('Installed native Piper. Authorized extension IDs: ' + ($ids -join ', '))
Write-Output 'Reload Call Translator at chrome://extensions, then refresh the Meet tab.'
