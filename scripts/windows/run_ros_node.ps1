param(
    [Parameter(Mandatory = $true)]
    [string]$Package,

    [Parameter(Mandatory = $true)]
    [string]$Executable,

    [int]$CameraIndex = -1,

    [string]$CameraBackend = 'dshow',

    [int]$CameraWidth = 1280,

    [int]$CameraHeight = 720,

    [string]$CameraFps = '30.0'
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$overlaySetup = Join-Path $repositoryRoot '.colcon-win\install\local_setup.ps1'
$ros2Runner = Join-Path $PSScriptRoot 'run_ros2.py'

if (-not (Test-Path -LiteralPath $overlaySetup)) {
    throw "ROS overlay를 찾을 수 없습니다: $overlaySetup"
}
if (-not (Test-Path -LiteralPath $ros2Runner)) {
    throw "ROS 2 실행 래퍼를 찾을 수 없습니다: $ros2Runner"
}

Set-Location -LiteralPath $repositoryRoot
. $overlaySetup
$env:RCUTILS_COLORIZED_OUTPUT = '0'

$rosArgs = @()
if ($CameraIndex -ge 0) {
    $rosArgs = @('--ros-args', '-p', "camera_index:=$CameraIndex", '-p', "camera_backend:=$CameraBackend", '-p', "width:=$CameraWidth", '-p', "height:=$CameraHeight", '-p', "camera_fps:=$CameraFps")
}

Write-Output "ROS 노드 시작: $Package / $Executable"
& python -X utf8 $ros2Runner run $Package $Executable @rosArgs
exit $LASTEXITCODE
