$ErrorActionPreference = 'Stop'

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$overlaySetup = Join-Path $repositoryRoot '.colcon-win\install\local_setup.ps1'
$bridgeRunner = Join-Path $PSScriptRoot 'run_rosbridge.py'

if (-not (Test-Path -LiteralPath $overlaySetup)) {
    throw "ROS overlay를 찾을 수 없습니다: $overlaySetup"
}

Set-Location -LiteralPath $repositoryRoot
. $overlaySetup
$env:RCUTILS_COLORIZED_OUTPUT = '0'
$env:PYTHONUNBUFFERED = '1'

Write-Output 'ROS overlay가 적용된 환경에서 rosbridge를 시작합니다.'
& python $bridgeRunner
exit $LASTEXITCODE
