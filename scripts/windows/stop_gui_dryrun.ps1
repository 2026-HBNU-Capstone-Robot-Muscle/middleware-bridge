$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$sessionFile = Join-Path $repositoryRoot 'logs\gui-dryrun\session.json'

if (-not (Test-Path -LiteralPath $sessionFile)) {
    Write-Host '기록된 GUI dry-run 세션이 없습니다.'
    exit 0
}

$session = Get-Content -LiteralPath $sessionFile -Raw | ConvertFrom-Json
$taskkill = Join-Path $env:WINDIR 'System32\taskkill.exe'
for ($index = $session.processes.Count - 1; $index -ge 0; $index -= 1) {
    $entry = $session.processes[$index]
    $processIdToStop = [int]$entry.process_id
    $process = Get-Process -Id $processIdToStop -ErrorAction SilentlyContinue
    if (-not $process) { continue }

    try {
        $expectedStart = [DateTime]::Parse($entry.started_at_utc).ToUniversalTime()
        $actualStart = $process.StartTime.ToUniversalTime()
        if ([Math]::Abs(($actualStart - $expectedStart).TotalSeconds) -ge 5) {
            Write-Warning "PID $processIdToStop가 다른 프로세스로 바뀐 것 같아 종료하지 않습니다."
            continue
        }
    }
    catch {
        Write-Warning "PID $processIdToStop 시작 시각을 확인하지 못해 종료하지 않습니다."
        continue
    }

    Write-Host "종료 중: $($entry.name) (PID $processIdToStop)"
    & $taskkill /PID $processIdToStop /T /F 2>$null | Out-Null
}

Remove-Item -LiteralPath $sessionFile -Force -ErrorAction SilentlyContinue
Write-Host 'GUI, rosbridge 및 dry-run ROS 노드를 종료했습니다.'
