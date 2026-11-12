param([Parameter(Mandatory=$true)][string]$PreparedDirectory, [string]$ToolchainDirectory, [string]$CCompilerDirectory)
$ErrorActionPreference = 'Stop'
$prepared = (Resolve-Path -LiteralPath $PreparedDirectory).Path
$manifest = Get-Content -LiteralPath (Join-Path $prepared 'build-manifest.json') -Raw | ConvertFrom-Json
$runtime = Join-Path $prepared 'runtime.zip'
if ((Get-FileHash -LiteralPath $runtime -Algorithm SHA256).Hash.ToLowerInvariant() -ne $manifest.prepared_runtime_sha256) {
    throw 'Prepared runtime SHA-256 mismatch'
}
$previous = @{}
try {
    foreach ($name in @('PATH','CARGO_HOME','RUSTUP_HOME','CARGO_BUILD_JOBS','CC','AR','CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER','PYAPP_INSTALL_DIR_CALL-TRANSLATOR-LOCAL','CT_LOCAL_VOICE_ROOT')) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
    }
    if (-not $ToolchainDirectory) {
        $candidate = Join-Path $PSScriptRoot '../.tools/rustup/toolchains/1.90.0-x86_64-pc-windows-gnu'
        if (Test-Path -LiteralPath (Join-Path $candidate 'bin/cargo.exe')) { $ToolchainDirectory = $candidate }
    }
    if ($ToolchainDirectory) {
        $toolchain = (Resolve-Path -LiteralPath $ToolchainDirectory).Path
        $env:PATH = (Join-Path $toolchain 'bin')+';'+$env:PATH
        $env:CARGO_HOME = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../.tools/cargo'))
        $env:RUSTUP_HOME = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../.tools/rustup'))
        $linker = Join-Path $toolchain 'lib/rustlib/x86_64-pc-windows-gnu/bin/self-contained/x86_64-w64-mingw32-gcc.exe'
        if (Test-Path -LiteralPath $linker) { $env:CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER = $linker }
    }
    if (-not $CCompilerDirectory) {
        $candidate = Join-Path $PSScriptRoot '../.tools/w64devkit/bin'
        if (Test-Path -LiteralPath (Join-Path $candidate 'gcc.exe')) { $CCompilerDirectory = $candidate }
    }
    if ($CCompilerDirectory) {
        $compiler = (Resolve-Path -LiteralPath $CCompilerDirectory).Path
        $env:PATH = $compiler+';'+$env:PATH
        $env:CC = Join-Path $compiler 'gcc.exe'
        $env:AR = Join-Path $compiler 'ar.exe'
    }
    if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
        throw 'Rust/Cargo and the Windows linker are required on the build machine'
    }
    $env:CARGO_BUILD_JOBS = '2'
    [Environment]::SetEnvironmentVariable('PYAPP_INSTALL_DIR_CALL-TRANSLATOR-LOCAL',(Join-Path $prepared 'self-test-runtime'),'Process')
    $env:CT_LOCAL_VOICE_ROOT = Join-Path $prepared 'self-test-voices'
    foreach ($entry in $manifest.environment.psobject.Properties) {
        $previous[$entry.Name] = [Environment]::GetEnvironmentVariable($entry.Name, 'Process')
        [Environment]::SetEnvironmentVariable($entry.Name, [string]$entry.Value, 'Process')
    }
    $buildRoot = Join-Path $prepared 'pyapp'
    # PyApp embeds environment-selected bytes without invalidating Cargo's cache.
    # Drop only this package's artifacts; keep its compiled dependencies.
    if ($env:CARGO_TARGET_DIR) {
        $sourceManifest = Get-ChildItem -Path (Join-Path $env:CARGO_HOME 'registry/src/*/pyapp-0.30.0/Cargo.toml') -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($sourceManifest) {
            & cargo clean --release --package pyapp --manifest-path $sourceManifest.FullName
            if ($LASTEXITCODE -ne 0) { throw 'Cannot invalidate embedded PyApp runtime' }
        }
    }
    & cargo install pyapp --version $manifest.pyapp_version --locked --root $buildRoot --force
    if ($LASTEXITCODE -ne 0) { throw 'PyApp build failed' }
    $executable = Join-Path $prepared 'CallTranslatorLocal.exe'
    Copy-Item -LiteralPath (Join-Path $buildRoot 'bin\pyapp.exe') -Destination $executable
    $executableHash=(Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
    [Environment]::SetEnvironmentVariable('PYAPP_INSTALL_DIR_CALL-TRANSLATOR-LOCAL',(Join-Path $prepared ('self-test-'+$executableHash.Substring(0,16))),'Process')
    $selfTest = & $executable --self-test
    if ($LASTEXITCODE -ne 0) { throw 'Local component self-test failed' }
    if (($selfTest | ConvertFrom-Json).version -ne $manifest.environment.PYAPP_PROJECT_VERSION) { throw 'Embedded local component version differs from prepared runtime' }
    Write-Output $selfTest
    $manifest.build_verified = $true
    $manifest | Add-Member -NotePropertyName rustc_version -NotePropertyValue ([string](& rustc --version)) -Force
    $manifest | Add-Member -NotePropertyName pyapp_executable_sha256 -NotePropertyValue (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant() -Force
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $prepared 'build-manifest.json') -Encoding UTF8
    Write-Output 'Build completed. Offline clean-Windows and Chrome tests are still required.'
} finally {
    foreach ($key in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($key, $previous[$key], 'Process')
    }
}
