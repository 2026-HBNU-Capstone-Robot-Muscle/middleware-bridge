$ErrorActionPreference = 'Stop'

function Write-Stage([string]$Message) {
    Write-Host "`n[Setup] $Message" -ForegroundColor Cyan
}

function Invoke-WingetInstall([string[]]$Arguments) {
    & winget @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "winget install command failed (exit code $LASTEXITCODE)."
    }
}

function Find-Pixi {
    $command = Get-Command pixi.exe, pixi -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA 'pixi\bin\pixi.exe'),
        (Join-Path $env:USERPROFILE '.pixi\bin\pixi.exe'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links\pixi.exe')
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) { return $candidate }
    }
    return $null
}

function Find-Cargo {
    $command = Get-Command cargo.exe, cargo -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($command) { return $command.Source }
    $candidate = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
    if (Test-Path -LiteralPath $candidate) { return $candidate }
    return $null
}

function Test-VcBuildTools {
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (-not (Test-Path -LiteralPath $vswhere)) { return $false }
    & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Out-Null
    return ($LASTEXITCODE -eq 0)
}

function Test-WebView2Runtime {
    $clientId = '{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
    $keys = @(
        "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$clientId",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$clientId",
        "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$clientId"
    )
    foreach ($key in $keys) {
        if (Test-Path -LiteralPath $key) {
            $version = (Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue).pv
            if ($version -and $version -ne '0.0.0.0') { return $true }
        }
    }
    return $false
}

function Add-UserToolPaths {
    $paths = @(
        (Join-Path $env:USERPROFILE '.cargo\bin'),
        (Join-Path $env:LOCALAPPDATA 'pixi\bin'),
        (Join-Path $env:USERPROFILE '.pixi\bin'),
        (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Links')
    )
    foreach ($path in $paths) {
        if ((Test-Path -LiteralPath $path) -and (($env:PATH -split ';') -notcontains $path)) {
            $env:PATH = "$path;$env:PATH"
        }
    }
}

try {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
    if ($repoRoot -match '[^\x20-\x7E]' -or $repoRoot.Contains(' ')) {
        throw '저장소 경로에 한글 등 비 ASCII 문자 또는 공백이 포함되어 있습니다. 저장소를 영문·숫자·하이픈만 사용하는 경로로 이동한 뒤 install.bat을 다시 실행하세요.'
    }
    Set-Location -LiteralPath $repoRoot

    if (-not [Environment]::Is64BitOperatingSystem) {
        throw '64-bit Windows is required.'
    }
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw 'winget was not found. Install Microsoft App Installer, then run install.bat again.'
    }

    Write-Stage 'Check and install Pixi'
    $pixi = Find-Pixi
    if (-not $pixi) {
        Invoke-WingetInstall @('install', '--id', 'prefix-dev.pixi', '--exact', '--accept-source-agreements', '--accept-package-agreements')
        Add-UserToolPaths
        $pixi = Find-Pixi
    }
    if (-not $pixi) { throw 'Pixi executable was not found after installation. Open a new PowerShell window and run install.bat again.' }
    & $pixi --version
    if ($LASTEXITCODE -ne 0) { throw 'Pixi failed to run.' }

    Write-Stage 'Check and install the Rust MSVC toolchain'
    $cargo = Find-Cargo
    if (-not $cargo) {
        Invoke-WingetInstall @('install', '--id', 'Rustlang.Rustup', '--exact', '--accept-source-agreements', '--accept-package-agreements')
        Add-UserToolPaths
        $cargo = Find-Cargo
    }
    if (-not $cargo) { throw 'Rust/Cargo executable was not found. Open a new PowerShell window and run install.bat again.' }
    $rustupCommand = Get-Command rustup.exe, rustup -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $rustupCommand) {
        $rustupPath = Join-Path $env:USERPROFILE '.cargo\bin\rustup.exe'
        if (Test-Path -LiteralPath $rustupPath) { $rustupCommand = Get-Item -LiteralPath $rustupPath }
    }
    if ($rustupCommand) {
        $rustupPath = if ($rustupCommand.Source) { $rustupCommand.Source } else { $rustupCommand.FullName }
        & $rustupPath default stable-msvc
        if ($LASTEXITCODE -ne 0) { throw 'Failed to select the Rust stable-msvc toolchain.' }
    }
    & $cargo --version
    if ($LASTEXITCODE -ne 0) { throw 'Cargo failed to run.' }

    Write-Stage 'Check and install Visual Studio C++ Build Tools'
    if (-not (Test-VcBuildTools)) {
        Invoke-WingetInstall @(
            'install', '--id', 'Microsoft.VisualStudio.2022.BuildTools', '--exact',
            '--accept-source-agreements', '--accept-package-agreements',
            '--override', '--wait --quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended --norestart'
        )
        if (-not (Test-VcBuildTools)) {
            throw 'Visual Studio C++ Build Tools were not detected. Add the Desktop development with C++ workload in Visual Studio Installer, then rerun install.bat.'
        }
    }

    Write-Stage 'Check and install WebView2 Runtime'
    if (-not (Test-WebView2Runtime)) {
        $bootstrapper = Join-Path $env:TEMP 'middleware-bridge-webview2-setup.exe'
        Invoke-WebRequest -Uri 'https://go.microsoft.com/fwlink/p/?LinkId=2124703' -OutFile $bootstrapper
        $process = Start-Process -FilePath $bootstrapper -ArgumentList '/silent', '/install' -Wait -PassThru
        if ($process.ExitCode -ne 0 -or -not (Test-WebView2Runtime)) {
            throw "WebView2 Runtime installation could not be verified (exit code $($process.ExitCode))."
        }
    }

    Write-Stage 'Check and install Tauri CLI'
    Add-UserToolPaths
    $tauri = Get-Command cargo-tauri.exe, cargo-tauri -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $tauri) {
        & $cargo install tauri-cli --locked
        if ($LASTEXITCODE -ne 0) { throw 'Tauri CLI installation failed.' }
        Add-UserToolPaths
        $tauri = Get-Command cargo-tauri.exe, cargo-tauri -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if (-not $tauri) { throw 'cargo-tauri executable was not found.' }
    & $tauri.Source --version

    Write-Stage 'Install the Pixi ROS 2 environment'
    & $pixi install
    if ($LASTEXITCODE -ne 0) { throw 'pixi install failed.' }

    Write-Stage 'Build ROS 2 packages'
    & $pixi run build-windows
    if ($LASTEXITCODE -ne 0) {
        $latestBuildLog = Get-ChildItem -LiteralPath '.colcon-win\log' -Directory -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending |
            Select-Object -First 1
        $interfaceStderr = if ($latestBuildLog) {
            Join-Path (Join-Path '.colcon-win\log' $latestBuildLog.Name) 'system_interfaces\stderr.log'
        }
        if ($interfaceStderr -and (Test-Path -LiteralPath $interfaceStderr)) {
            Write-Stage 'system_interfaces 빌드 stderr 로그 (마지막 80줄)'
            Get-Content -LiteralPath $interfaceStderr -Encoding UTF8 -Tail 80
        }
        throw 'ROS 2 package build failed. See the system_interfaces stderr shown above and .colcon-win\log for the full build log.'
    }

    Write-Stage 'Build the static Tauri frontend'
    & powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File '.\apps\monitoring_ui\scripts\build.ps1'
    if ($LASTEXITCODE -ne 0) { throw 'Static Tauri frontend generation failed.' }

    Write-Host "`nEnvironment setup and ROS package build completed." -ForegroundColor Green
    Write-Host 'Run start.bat to launch the desktop dry-run GUI.'
    exit 0
}
catch {
    Write-Host "`nSetup failed: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
