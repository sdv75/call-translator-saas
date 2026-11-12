# Portable build tools only. No system PATH, Rustup profile, or native-host registration.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'build-toolchain-lock.json') -Raw | ConvertFrom-Json
$downloads = Join-Path $root '.tools/build-toolchain'
New-Item -ItemType Directory -Force -Path $downloads | Out-Null

function Get-VerifiedTool($record, $name) {
    $file = Join-Path $downloads $name
    if (-not (Test-Path -LiteralPath $file)) {
        Invoke-WebRequest -UseBasicParsing -Uri $record.url -OutFile $file
    }
    if ((Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant() -ne $record.sha256) {
        throw "Build tool SHA-256 mismatch: $name"
    }
    return $file
}

$rustup = Get-VerifiedTool $lock.rustup 'rustup-init.exe'
$gccArchive = Get-VerifiedTool $lock.c_compiler 'w64devkit-x64-2.5.0.7z.exe'
$innoInstaller = Get-VerifiedTool $lock.inno 'innosetup-6.7.4.exe'
$signature = Get-AuthenticodeSignature -LiteralPath $innoInstaller
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch [regex]::Escape($lock.inno.authenticode_publisher)) {
    throw 'Inno Setup publisher signature is not valid'
}
$previous = @{}
try {
    foreach ($name in @('RUSTUP_HOME','CARGO_HOME')) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    $env:RUSTUP_HOME = Join-Path $root '.tools/rustup'
    $env:CARGO_HOME = Join-Path $root '.tools/cargo'
    # Invoking as rustup.exe uses the manager directly; no global self-install.
    $manager = Join-Path $downloads 'rustup.exe'
    Copy-Item -LiteralPath $rustup -Destination $manager
    & $manager toolchain install $lock.rust_toolchain --profile minimal --component rust-mingw --no-self-update
    if ($LASTEXITCODE) { throw 'Portable Rust toolchain preparation failed' }
    $tools = Join-Path $root '.tools'
    if (-not (Test-Path -LiteralPath (Join-Path $tools 'w64devkit/bin/gcc.exe'))) {
        $process = Start-Process -FilePath $gccArchive -ArgumentList @('-y',('-o"'+$tools+'"')) -WindowStyle Hidden -PassThru -Wait
        if ($process.ExitCode) { throw 'Portable C compiler extraction failed' }
    }
    $inno = Join-Path $tools 'inno-6.7.4'
    if (-not (Test-Path -LiteralPath (Join-Path $inno 'ISCC.exe'))) {
        $process = Start-Process -FilePath $innoInstaller -ArgumentList @('/PORTABLE=1','/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR="'+$inno+'"')) -WindowStyle Hidden -PassThru -Wait
        if ($process.ExitCode) { throw 'Portable Inno compiler preparation failed' }
    }
    Write-Output 'Portable build tools ready under .tools. Global PATH and native-host registration were not changed.'
} finally {
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
}
