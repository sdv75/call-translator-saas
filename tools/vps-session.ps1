# Connection values stay in memory. History use requires the user's explicit approval.
param([Parameter(Mandatory=$true)][string]$ApprovedHistory)
$ErrorActionPreference = 'Stop'
$script:VpsPlink = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../.tools/deploy-tools/plink.exe'))
function Quote-VpsArgument([string]$value) {
    return '"'+([regex]::Replace($value,'(\\*)"','$1$1\"') -replace '(\\+)$','$1$1')+'"'
}
function Invoke-VpsProcess([string]$Command, [byte[]]$InputBytes, [string]$InputFile) {
    $info = New-Object Diagnostics.ProcessStartInfo
    $info.FileName = $script:VpsPlink
    $info.Arguments = (@('-batch','-ssh','-i',$script:VpsKey,$script:VpsTarget,$Command) | ForEach-Object {Quote-VpsArgument $_}) -join ' '
    $info.UseShellExecute=$false; $info.CreateNoWindow=$true
    $info.RedirectStandardInput=$true; $info.RedirectStandardOutput=$true; $info.RedirectStandardError=$true
    $process = New-Object Diagnostics.Process; $process.StartInfo=$info
    [void]$process.Start()
    $stdout=$process.StandardOutput.ReadToEndAsync(); $stderr=$process.StandardError.ReadToEndAsync()
    try {
        if ($InputFile) { $stream=[IO.File]::OpenRead((Resolve-Path -LiteralPath $InputFile).Path); try {$stream.CopyTo($process.StandardInput.BaseStream)} finally {$stream.Dispose()} }
        elseif ($InputBytes) { $process.StandardInput.BaseStream.Write($InputBytes,0,$InputBytes.Length) }
    } finally {$process.StandardInput.Close()}
    $process.WaitForExit()
    $result=[pscustomobject]@{ExitCode=$process.ExitCode;Output=$stdout.GetAwaiter().GetResult();Error=$stderr.GetAwaiter().GetResult()}
    $process.Dispose(); return $result
}
function Invoke-Vps([string]$Command, [byte[]]$InputBytes, [string]$InputFile) {
    $result=Invoke-VpsProcess $Command $InputBytes $InputFile
    if ($result.ExitCode -ne 0) {throw "VPS command failed (exit $($result.ExitCode)); connection details suppressed"}
    return $result.Output
}
$history=[IO.File]::ReadAllText((Resolve-Path -LiteralPath $ApprovedHistory).Path)
$keys=@([regex]::Matches($history,'[A-Za-z]:[\\/][^"''\r\n<>|]*?\.ppk') | ForEach-Object {$_.Value.Replace('\\','\')} | Sort-Object -Unique | Where-Object {Test-Path -LiteralPath $_ -PathType Leaf})
$targets=@([regex]::Matches($history,'root@[A-Za-z0-9._-]+') | ForEach-Object {$_.Value} | Sort-Object -Unique)
$cached=(Get-Item 'HKCU:/Software/SimonTatham/PuTTY/SshHostKeys').Property
$script:VpsTarget=$targets | Where-Object {$candidate=$_.Substring(5);@($cached | Where-Object {$_.EndsWith(':'+$candidate)}).Count -gt 0} | Select-Object -First 1
if(-not $script:VpsTarget){throw 'No explicitly approved target with cached host key'}
$connected=$false
foreach($key in $keys){
    $script:VpsKey=$key
    $probe=Invoke-VpsProcess 'printf SSH_OK' $null $null
    if($probe.ExitCode -eq 0 -and $probe.Output -eq 'SSH_OK'){$connected=$true;break}
}
if(-not $connected){throw 'Approved SSH authentication failed; no credentials printed'}
