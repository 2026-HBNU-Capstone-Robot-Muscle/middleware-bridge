param(
    [ValidateSet('mock', 'read_only')]
    [string]$Mode = 'mock',
    [string]$Port = ''
)

$ErrorActionPreference = 'Stop'
$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$overlaySetup = Join-Path $repositoryRoot '.colcon-win\install\local_setup.ps1'
if (-not (Test-Path -LiteralPath $overlaySetup)) {
    throw "ROS overlay not found. Build the workspace first: $overlaySetup"
}
if ($Mode -eq 'read_only' -and [string]::IsNullOrWhiteSpace($Port)) {
    throw 'read_only requires an explicit -Port; the port depends on this PC.'
}
Set-Location -LiteralPath $repositoryRoot
. $overlaySetup
$rosArguments = @('--ros-args', '-p', "backend_mode:=$Mode")
if ($Mode -eq 'read_only') {
    $rosArguments += @('-p', "port:=$Port")
}
Write-Output "LEAP adapter mode=$Mode. Stop the old leap_hand_primitive_server first."
& ros2 run leap_hand_control leap_hand_adapter @rosArguments
exit $LASTEXITCODE
