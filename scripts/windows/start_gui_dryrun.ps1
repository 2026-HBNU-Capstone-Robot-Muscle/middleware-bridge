param(
    [int]$CameraIndex = 0,
    [ValidateSet('dshow', 'msmf', 'any')]
    [string]$CameraBackend = 'dshow',
    [ValidateRange(1, 7680)]
    [int]$CameraWidth = 1280,
    [ValidateRange(1, 4320)]
    [int]$CameraHeight = 720,
    [ValidateRange(1, 240)]
    [double]$CameraFps = 30.0
)

$ErrorActionPreference = 'Stop'
$CameraBackend = $CameraBackend.ToLowerInvariant()

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$logDirectory = Join-Path $repositoryRoot 'logs\gui-dryrun'
$sessionFile = Join-Path $logDirectory 'session.json'
$rosRunner = Join-Path $PSScriptRoot 'run_ros_node.ps1'
$overlaySetup = Join-Path $repositoryRoot '.colcon-win\install\local_setup.ps1'
$frontendBuild = Join-Path $repositoryRoot 'apps\monitoring_ui\scripts\build.ps1'
$tauriDirectory = Join-Path $repositoryRoot 'apps\monitoring_ui\src-tauri'
$script:ManagedProcesses = @()

function Write-Stage {
    param([string]$Message)
    Write-Host "[GUI dry-run] $Message" -ForegroundColor Cyan
}

function Test-TcpPortOpen {
    param(
        [string]$HostName,
        [int]$Port
    )

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $connect = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne(350)) {
            return $false
        }
        $client.EndConnect($connect)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

function Get-ApplicationPath {
    param([string]$Name)

    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($command) {
        return $command.Source
    }
    return $null
}

function Get-QuotedArgumentLine {
    param([string[]]$ArgumentList)

    return (($ArgumentList | ForEach-Object {
        $argument = [string]$_
        if ($argument.Contains(' ') -or $argument.Contains('"')) {
            '"' + $argument.Replace('"', '\"') + '"'
        }
        else {
            $argument
        }
    }) -join ' ')
}

function Stop-StartedProcesses {
    for ($index = $script:ManagedProcesses.Count - 1; $index -ge 0; $index -= 1) {
        $entry = $script:ManagedProcesses[$index]
        if (-not $entry.Process -or $entry.Process.HasExited) {
            continue
        }
        Write-Stage "시작한 프로세스 정리: $($entry.Name)"
        & taskkill.exe /PID $entry.Process.Id /T /F 2>$null | Out-Null
    }
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory
    )

    $safeName = $Name -replace '[^a-zA-Z0-9_-]', '_'
    $stdoutPath = Join-Path $logDirectory "$safeName.out.log"
    $stderrPath = Join-Path $logDirectory "$safeName.err.log"
    Remove-Item -LiteralPath $stdoutPath, $stderrPath -Force -ErrorAction SilentlyContinue
    $arguments = Get-QuotedArgumentLine -ArgumentList $ArgumentList
    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $arguments `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -RedirectStandardOutput $stdoutPath `
        -RedirectStandardError $stderrPath `
        -PassThru
    $entry = [pscustomobject]@{
        Name = $Name
        Process = $process
        Stdout = $stdoutPath
        Stderr = $stderrPath
    }
    $script:ManagedProcesses += $entry
    Write-Stage "$Name 시작됨 (PID $($process.Id))"
    return $entry
}

function Wait-ForLogText {
    param(
        [pscustomobject]$Entry,
        [string]$ExpectedText,
        [int]$TimeoutSeconds = 35
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $Entry.Process.Refresh()
        if ($Entry.Process.HasExited) {
            $stderr = if (Test-Path -LiteralPath $Entry.Stderr) {
                Get-Content -LiteralPath $Entry.Stderr -Raw -ErrorAction SilentlyContinue
            }
            else { '' }
            throw "$($Entry.Name)이 시작 중 종료되었습니다. 로그: $($Entry.Stderr) $stderr"
        }
        foreach ($path in @($Entry.Stdout, $Entry.Stderr)) {
            if (Test-Path -LiteralPath $path) {
                $content = Get-Content -LiteralPath $path -Raw -ErrorAction SilentlyContinue
                if ($content -and $content.Contains($ExpectedText)) {
                    return
                }
            }
        }
        Start-Sleep -Milliseconds 500
    }
    throw "$($Entry.Name) 준비 상태를 확인하지 못했습니다. 로그: $($Entry.Stdout)"
}

function Test-PreviousSessionActive {
    if (-not (Test-Path -LiteralPath $sessionFile)) {
        return $false
    }
    $oldSession = Get-Content -LiteralPath $sessionFile -Raw | ConvertFrom-Json
    foreach ($entry in @($oldSession.processes)) {
        $process = Get-Process -Id ([int]$entry.process_id) -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        try {
            $expectedStart = [DateTime]::Parse($entry.started_at_utc).ToUniversalTime()
            $actualStart = $process.StartTime.ToUniversalTime()
            if ([Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -lt 5) {
                return $true
            }
        }
        catch {
            continue
        }
    }
    return $false
}

try {
    if (Test-PreviousSessionActive) {
        throw "이 실행기 세션이 이미 켜져 있습니다. 먼저 저장소 루트의 stop.bat을 실행하세요."
    }
    if (-not (Test-Path -LiteralPath $overlaySetup)) {
        throw "ROS 패키지 빌드 결과가 없습니다. 저장소 루트에서 pixi run build-windows를 먼저 실행하세요."
    }
    if (-not (Test-Path -LiteralPath $rosRunner)) {
        throw "ROS 노드 실행 스크립트를 찾을 수 없습니다: $rosRunner"
    }
    if (Test-TcpPortOpen -HostName '127.0.0.1' -Port 9090) {
        throw '9090 포트가 이미 사용 중입니다. 기존 rosbridge 또는 실행기 세션을 확인한 뒤 다시 실행하세요.'
    }

    $pixi = Get-ApplicationPath -Name 'pixi.exe'
    if (-not $pixi) { $pixi = Get-ApplicationPath -Name 'pixi' }
    if (-not $pixi) { throw 'pixi를 찾을 수 없습니다. Pixi 설치와 PATH를 확인하세요.' }

    $cargo = Get-ApplicationPath -Name 'cargo.exe'
    if (-not $cargo) {
        $userCargo = Join-Path $env:USERPROFILE '.cargo\bin\cargo.exe'
        if (Test-Path -LiteralPath $userCargo) { $cargo = $userCargo }
    }
    if (-not $cargo) { throw 'Cargo를 찾을 수 없습니다. Rust/Cargo 설치를 확인하세요.' }

    New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
    Write-Stage '정적 GUI 파일 준비 중'
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $frontendBuild
    if ($LASTEXITCODE -ne 0) { throw '정적 GUI 빌드에 실패했습니다.' }

    $rosbridge = Start-ManagedProcess `
        -Name 'rosbridge' `
        -FilePath $pixi `
        -ArgumentList @('run', 'rosbridge') `
        -WorkingDirectory $repositoryRoot

    $portDeadline = (Get-Date).AddSeconds(35)
    while (-not (Test-TcpPortOpen -HostName '127.0.0.1' -Port 9090)) {
        $rosbridge.Process.Refresh()
        if ($rosbridge.Process.HasExited) {
            throw "rosbridge가 시작 중 종료되었습니다. 로그: $($rosbridge.Stderr)"
        }
        if ((Get-Date) -ge $portDeadline) {
            throw "rosbridge가 9090 포트에서 준비되지 않았습니다. 로그: $($rosbridge.Stdout)"
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Stage 'rosbridge 준비 완료 (127.0.0.1:9090)'

    $cameraFpsArgument = $CameraFps.ToString('0.0##', [Globalization.CultureInfo]::InvariantCulture)
    $nodeSpecs = @(
        @{ Name = 'cube_solver'; Package = 'cube_solver'; Executable = 'cube_solver'; Ready = 'Cube solver service ready: /cube/solve' },
        @{ Name = 'cube_detector'; Package = 'cube_detection'; Executable = 'cube_detector'; Ready = 'Loaded YOLO model' },
        @{ Name = 'leap_hand_dryrun'; Package = 'leap_hand_control'; Executable = 'leap_hand_primitive_server'; Ready = 'Ready: /leap_hand/execute_primitive' },
        @{ Name = 'custom_hand_dryrun'; Package = 'custom_hand_control'; Executable = 'custom_hand_primitive_server'; Ready = 'Ready: /custom_hand/execute_primitive' },
        @{ Name = 'cube_executor_dryrun'; Package = 'cube_execution'; Executable = 'cube_sequence_executor'; Ready = 'Ready: /cube/execute_solution' }
    )
    foreach ($spec in $nodeSpecs) {
        $runnerArguments = @(
            'run', 'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
            '-File', $rosRunner, '-Package', $spec.Package, '-Executable', $spec.Executable
        )
        $node = Start-ManagedProcess `
            -Name $spec.Name `
            -FilePath $pixi `
            -ArgumentList $runnerArguments `
            -WorkingDirectory $repositoryRoot
        Wait-ForLogText -Entry $node -ExpectedText $spec.Ready
        Write-Stage "$($spec.Name) 준비 완료"
    }

    $cameraManagerArguments = @(
        'run', 'powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass',
        '-File', $rosRunner, '-Package', 'cube_detection', '-Executable', 'cube_camera_manager',
        '-CameraIndex', [string]$CameraIndex,
        '-CameraBackend', $CameraBackend,
        '-CameraWidth', [string]$CameraWidth,
        '-CameraHeight', [string]$CameraHeight,
        '-CameraFps', $cameraFpsArgument
    )
    $cameraManager = Start-ManagedProcess `
        -Name 'cube_camera_manager' `
        -FilePath $pixi `
        -ArgumentList $cameraManagerArguments `
        -WorkingDirectory $repositoryRoot
    Wait-ForLogText -Entry $cameraManager -ExpectedText 'Camera manager ready: /cube/list_cameras and /cube/set_camera_enabled.'
    Write-Stage '카메라 관리 서비스 준비 완료 (GUI 버튼에서 시작 가능)'

    $tauri = Start-ManagedProcess `
        -Name 'tauri_desktop' `
        -FilePath $cargo `
        -ArgumentList @('tauri', 'dev') `
        -WorkingDirectory $tauriDirectory

    Start-Sleep -Seconds 2
    $tauri.Process.Refresh()
    if ($tauri.Process.HasExited) {
        throw "Tauri 앱이 시작 중 종료되었습니다. 로그: $($tauri.Stderr)"
    }

    $session = @{
        repository_root = $repositoryRoot
        started_at_utc = [DateTime]::UtcNow.ToString('o')
        processes = @($script:ManagedProcesses | ForEach-Object {
            $_.Process.Refresh()
            @{
                name = $_.Name
                process_id = $_.Process.Id
                started_at_utc = $_.Process.StartTime.ToUniversalTime().ToString('o')
            }
        })
    }
    $session | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $sessionFile -Encoding UTF8

    Write-Host ''
    Write-Stage '데스크톱 GUI와 ROS dry-run 서버가 준비되었습니다.'
    Write-Host 'GUI에서 연결 상태를 확인한 뒤 스캔하거나 저장된 풀이를 발행하세요.'
    Write-Host "로그: $logDirectory"
    Write-Host '종료할 때는 저장소 루트의 stop.bat을 실행하세요.'
}
catch {
    Write-Host "[GUI dry-run 오류] $($_.Exception.Message)" -ForegroundColor Red
    Stop-StartedProcesses
    exit 1
}
