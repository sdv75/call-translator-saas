param([Parameter(Mandatory=$true)][string]$BackupPath, [switch]$Restore)
$ErrorActionPreference = 'Stop'
$keys = @(
    'HKCU:\Software\Chromium\NativeMessagingHosts\org.call_translator.piper',
    'HKCU:\Software\Google\ChromeForTesting\NativeMessagingHosts\org.call_translator.piper'
)
if ($Restore) {
    $backups = Get-Content -LiteralPath $BackupPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($backup in $backups) {
        if ($keys -notcontains $backup.key) { throw 'Unexpected registry backup target.' }
        if ($backup.exists) {
            New-Item -Path $backup.key -Force | Out-Null
            if ($null -ne $backup.value) { Set-Item -LiteralPath $backup.key -Value $backup.value }
            else { Remove-ItemProperty -LiteralPath $backup.key -Name '(default)' -ErrorAction SilentlyContinue }
        } elseif (Test-Path -LiteralPath $backup.key) {
            # This exact app-specific key was created only for the temporary browser test.
            Remove-Item -LiteralPath $backup.key -Force
        }
    }
    'Temporary browser registration restored.'
    exit
}
if (Test-Path -LiteralPath $BackupPath) { throw 'Registry backup already exists.' }
$primary = Get-Item -LiteralPath 'HKCU:\Software\Google\Chrome\NativeMessagingHosts\org.call_translator.piper'
$manifest = $primary.GetValue('')
if (-not (Test-Path -LiteralPath $manifest)) { throw 'Install native Piper before running this test.' }
$backups = @($keys | ForEach-Object {
    $entry = Get-Item -LiteralPath $_ -ErrorAction SilentlyContinue
    @{key = $_; exists = [bool]$entry; value = $(if ($entry) { $entry.GetValue('') } else { $null })}
})
[IO.File]::WriteAllText($BackupPath, ($backups | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
foreach ($key in $keys) {
    New-Item -Path $key -Force | Out-Null
    Set-Item -LiteralPath $key -Value $manifest
}
'Temporary browser registration prepared.'
